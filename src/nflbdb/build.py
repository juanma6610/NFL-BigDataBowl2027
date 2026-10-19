"""Raw CSV -> cleaned, enriched parquet (data/raw -> data/processed).

Principles
----------
- Raw CSVs are never modified; every output can be rebuilt from them with one command.
- Fix what is objectively wrong: dtypes, duplicate drill names, the Combine `dis` column,
  BALL rows mixed into player tracking, a typo'd column name, the Rams' two team codes.
- Flag, don't drop: preseason/postseason, truncated reps, plays killed pre-snap, Combine
  opt-outs and unmatched join keys all stay in, with a column that says so. Filtering is
  an analysis decision, made at load time.
- Wide where it's cheap (players, plays), narrow where it's big (tracking): game tracking
  only carries what you need per frame; join play context at query time.

Outputs (data/processed/)
-------------------------
players.parquet              1 row / prospect: bio + draft + combine results + career + derived
games.parquet                1 row / game
plays.parquet                1 row / (game, play, rookie): player_play + game context + derived
combine_tracking.parquet     10 Hz Combine drills, PLAYER rows only, with frame / t / fixed dis
combine_ball.parquet         10 Hz Combine BALL rows (WR/TE drills only)
game_tracking_{season}.parquet  10 Hz in-game tracking, rookies only, + standardised coords
manifest.json                raw file hashes, output row counts, data checks, drill-name catalogue
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

import polars as pl

NULLS = ["NA", "NULL", "null", "None", ""]
TIME_FMT = "%Y-%m-%dT%H:%M:%S%.f"
SEASONS = (2023, 2024, 2025)
LAST_SEASON = max(SEASONS)
FIELD_LENGTH, FIELD_WIDTH = 120.0, 53.3
SNAP_EVENTS = ["ball_snap", "snap_direct"]

F32, I16, I32, I64, STR, CAT = pl.Float32, pl.Int16, pl.Int32, pl.Int64, pl.String, pl.Categorical

# Types for the big tracking files. schema_overrides (not schema) so the CSV header still
# decides column names/order; we only pin dtypes and skip the inference pass.
COMBINE_TYPES: dict[str, pl.DataType] = {
    "draft_year": I16, "event_id": STR, "nfl_id": I32, "entity_type": STR, "time": STR,
    "drill_type": STR, "drill_name": STR, "attempt": I16,
    "x": F32, "y": F32, "s": F32, "a": F32, "dis": F32, "dir": F32,
}  # fmt: skip
GAME_TYPES: dict[str, pl.DataType] = {
    "game_id": I64, "play_id": I32, "nfl_id": I32, "time": STR,
    "x": F32, "y": F32, "s": F32, "a": F32, "dis": F32, "o": F32, "dir": F32, "event": STR,
}  # fmt: skip

# Same drill exported under two spellings (see docs/RESOURCES.md §2). Left -> right.
DRILL_NAME_FIXES = {
    "PASS_PRO-MIRROR_DRILL": "PASS_PRO_MIRROR_DRILL",
    "OVER_SHOULDER_ADJUST": "OVER_THE_SHOULDER_ADJUST",
    "LINE": "LINE_DRILL",
    "SPEED_OUT_LEFT": "SPEED_OUT_ROUTE_LEFT",
    "SPEED_OUT_RIGHT": "SPEED_OUT_ROUTE_RIGHT",
}
# 2024 reps of this drill stop before the break (braking phase missing). Flagged, not dropped.
TRUNCATED_DRILLS = {(2024, "BACK_PEDAL_AND_TRANSITION_45_DEGREE_REACTION")}

ID_TYPES = {"game_id": I64, "play_id": I32, "nfl_id": I32, "draft_year": I16, "season": I16}
COLUMN_FIXES = {"visitor_team_win_probility_added": "visitor_team_win_probability_added"}
# The Rams are "LA" in 2023-24 and "LAR" in 2025: one team, 33 codes. Left -> right.
TEAM_FIXES = {"LA": "LAR"}
TEAM_COLS = ["team_abbr", "possession_team", "yardline_side", "home_team_abbr", "visitor_team_abbr"]
COMBINE_TESTS = [
    "ten_yd_split", "forty", "vertical", "broad_jump", "three_cone", "short_shuttle", "bench_reps",
]  # fmt: skip
CAT_COLS = [
    "nfl_position", "combine_position", "college_conference", "team_abbr", "possession_team",
    "lined_up_position", "offense_formation", "receiver_alignment", "pass_result",
    "team_coverage_man_zone", "team_coverage_type", "route_ran", "coverage_assignment",
    "coverage_assignment_at_snap", "season_type", "play_direction", "home_team_abbr",
    "visitor_team_abbr", "yardline_side", "drill_type", "drill_name", "event",
]  # fmt: skip


# --------------------------------------------------------------------------- checks
@dataclass
class Report:
    checks: list[dict] = field(default_factory=list)
    outputs: dict[str, dict] = field(default_factory=dict)
    extra: dict = field(default_factory=dict)

    def check(self, name: str, ok: bool, detail: str = "") -> None:
        self.checks.append({"check": name, "ok": bool(ok), "detail": detail})
        print(f"  {'ok  ' if ok else 'WARN'}  {name}{'  - ' + detail if detail else ''}")

    def note(self, name: str, detail: str) -> None:
        self.checks.append({"check": name, "ok": None, "detail": detail})
        print(f"  info  {name}  - {detail}")


def _unique(df: pl.DataFrame, keys: list[str], label: str, rep: Report) -> None:
    dupes = df.height - df.select(keys).unique().height
    rep.check(f"{label}: ({', '.join(keys)}) unique", dupes == 0, f"{dupes:,} duplicate rows")


# --------------------------------------------------------------------------- helpers
def _find(raw: Path, stem: str) -> Path:
    hits = sorted(raw.rglob(f"{stem}.csv"))
    if not hits:
        raise FileNotFoundError(f"{stem}.csv not found under {raw}. Download the data first.")
    return hits[0]


def _read_small(raw: Path, stem: str) -> pl.DataFrame:
    """Small tables: full-file schema inference, ISO dates, and True/False/Y/N -> Boolean."""
    df = pl.read_csv(_find(raw, stem), infer_schema_length=None, null_values=NULLS)
    df = df.rename({k: v for k, v in COLUMN_FIXES.items() if k in df.columns})
    casts = []
    for name, dtype in df.schema.items():
        if dtype != pl.String:
            continue
        vals = set(df[name].drop_nulls().unique().str.to_lowercase().to_list())
        if vals and vals <= {"true", "false"}:
            casts.append(pl.col(name).str.to_lowercase().eq("true").alias(name))
        elif vals and vals <= {"y", "n"}:
            casts.append(pl.col(name).str.to_lowercase().eq("y").alias(name))
    if "birth_date" in df.columns and df.schema["birth_date"] == pl.String:
        casts.append(pl.col("birth_date").str.to_date("%Y-%m-%d", strict=False))
    # Same key dtypes as the tracking files, so joins never upcast.
    casts += [pl.col(c).cast(t) for c, t in ID_TYPES.items() if c in df.columns]
    casts += [pl.col(c).replace(TEAM_FIXES) for c in TEAM_COLS if c in df.columns]
    return df.with_columns(casts) if casts else df


def _categorize(df: pl.DataFrame) -> pl.DataFrame:
    cols = [c for c in CAT_COLS if c in df.columns and df.schema[c] == pl.String]
    return df.with_columns(pl.col(cols).cast(CAT)) if cols else df


def _seconds(delta: pl.Expr) -> pl.Expr:
    return (delta.dt.total_milliseconds() / 1000).cast(F32)


def _write(df: pl.DataFrame, out: Path, name: str, rep: Report) -> None:
    path = out / f"{name}.parquet"
    df.write_parquet(path, compression="zstd", statistics=True)
    mib = path.stat().st_size / 2**20
    rep.outputs[name] = {"rows": df.height, "cols": df.width, "mib": round(mib, 1)}
    print(f"  ->    {path.name:30s} {df.height:>12,} rows  {df.width:>3} cols  {mib:8.1f} MiB")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# --------------------------------------------------------------------------- tables
def build_games(raw: Path, rep: Report) -> pl.DataFrame:
    games = _read_small(raw, "games")
    _unique(games, ["game_id"], "games", rep)
    counts = games.group_by("season", "season_type").len().sort("season", "season_type")
    rep.note("games by season/type", ", ".join(f"{s} {t}: {n}" for s, t, n in counts.rows()))
    return games


def build_plays_base(raw: Path, games: pl.DataFrame, draft_years: pl.DataFrame, rep: Report):
    """player_play + game context + derived situation columns (has_tracking added later)."""
    pp = _read_small(raw, "player_play")
    _unique(pp, ["game_id", "play_id", "nfl_id"], "player_play", rep)
    missing_games = pp.join(games, on="game_id", how="anti").select("game_id").n_unique()
    rep.check("player_play: every game_id in games", missing_games == 0, f"{missing_games} missing")

    game_cols = ["game_id", "season", "season_type", "week", "home_team_abbr", "visitor_team_abbr"]
    pp = pp.join(games.select(game_cols), on="game_id", how="left").join(
        draft_years, on="nfl_id", how="left"
    )

    is_home = pl.col("team_abbr") == pl.col("home_team_abbr")
    clock = pl.col("game_clock").str.split(":")
    clock_s = clock.list.get(0).cast(I32) * 60 + clock.list.get(1).cast(I32)
    own_half = pl.col("yardline_side") == pl.col("possession_team")
    derived = {
        # situation
        "is_offense": pl.col("team_abbr") == pl.col("possession_team"),
        "is_dropback": pl.col("pass_result").is_not_null(),
        "pre_snap_dead": pl.col("lined_up_position").is_null(),  # host: "NA" = killed pre-snap
        "quarter_seconds_remaining": clock_s,
        "game_seconds_remaining": pl.when(pl.col("quarter") <= 4)
        .then((4 - pl.col("quarter")) * 900 + clock_s)
        .otherwise(clock_s),
        "yardline_100": pl.when(pl.col("yardline_number") == 50)
        .then(50)
        .when(own_half)
        .then(100 - pl.col("yardline_number"))
        .otherwise(pl.col("yardline_number")),
        "team_score": pl.when(is_home)
        .then(pl.col("pre_snap_home_score"))
        .otherwise(pl.col("pre_snap_visitor_score")),
        "opp_score": pl.when(is_home)
        .then(pl.col("pre_snap_visitor_score"))
        .otherwise(pl.col("pre_snap_home_score")),
        "team_win_probability": pl.when(is_home)
        .then(pl.col("pre_snap_home_team_win_probability"))
        .otherwise(pl.col("pre_snap_visitor_team_win_probability")),
        # career timing
        "season_of_career": (pl.col("season") - pl.col("draft_year") + 1).cast(I16),
    }
    pp = pp.with_columns(**{k: v for k, v in derived.items() if _cols_ok(v, pp)})
    if {"team_score", "opp_score"} <= set(pp.columns):
        pp = pp.with_columns(score_diff=pl.col("team_score") - pl.col("opp_score"))
    pp = pp.with_columns(is_rookie_season=pl.col("season_of_career") == 1).drop("draft_year")

    dirs = pp.group_by("game_id", "play_id").agg(pl.col("play_direction").n_unique().alias("n"))
    conflicts = dirs.filter(pl.col("n") > 1).height
    rep.check("player_play: one play_direction per play", conflicts == 0, f"{conflicts} conflicts")
    return pp


def _cols_ok(expr: pl.Expr, df: pl.DataFrame) -> bool:
    """Skip a derived column if the CSV lacks one of its inputs (keeps the build robust)."""
    return set(expr.meta.root_names()) <= set(df.columns)


def build_combine_tracking(raw: Path, positions: pl.DataFrame, rep: Report):
    df = (
        pl.scan_csv(
            _find(raw, "combine_tracking"), schema_overrides=COMBINE_TYPES, null_values=NULLS
        )
        .with_columns(
            pl.col("time").str.to_datetime(TIME_FMT, strict=False),
            drill_name_raw=pl.col("drill_name"),
            drill_name=pl.col("drill_name").replace(DRILL_NAME_FIXES),
        )
        .collect()
    )
    rep.check(
        "combine: no unparsed timestamps",
        df["time"].null_count() == 0,
        f"{df['time'].null_count():,} null",
    )

    catalogue = (
        df.filter(pl.col("entity_type") == "PLAYER")
        .group_by("drill_type", "drill_name_raw", "drill_name")
        .agg(
            attempts=pl.struct("event_id", "nfl_id").n_unique(),
            draft_years=pl.col("draft_year").unique().sort(),
        )
        .sort("drill_type", "drill_name")
    )
    rep.extra["drill_catalogue"] = catalogue.to_dicts()
    renamed = catalogue.filter(pl.col("drill_name") != pl.col("drill_name_raw")).height
    rep.note("combine: drill names normalised", f"{renamed} raw spellings merged")

    keys = ["event_id", "nfl_id"]
    ball = df.filter(pl.col("entity_type") == "BALL").drop("entity_type", "drill_name_raw")
    ball = ball.sort(*keys, "time").with_columns(frame=pl.int_range(pl.len(), dtype=I16).over(keys))

    player = df.filter(pl.col("entity_type") == "PLAYER").drop("entity_type").sort(*keys, "time")
    step = (pl.col("x").diff().over(keys) ** 2 + pl.col("y").diff().over(keys) ** 2).sqrt()
    truncated = pl.lit(False)
    for year, drill in TRUNCATED_DRILLS:
        truncated = truncated | ((pl.col("draft_year") == year) & (pl.col("drill_name") == drill))
    player = player.with_columns(
        frame=pl.int_range(pl.len(), dtype=I16).over(keys),
        t=_seconds(pl.col("time") - pl.col("time").first().over(keys)),
        dis_raw=pl.col("dis"),  # provided column behaves like a squared step: don't sum it
        dis=step.fill_null(0.0).cast(F32),
        quantized=pl.col("draft_year") < 2025,  # 2023-24 exports sit on a coarse grid
        truncated_rep=truncated,
    ).join(positions, on="nfl_id", how="left")

    order = [
        "draft_year",
        "event_id",
        "nfl_id",
        "combine_position",
        "drill_type",
        "drill_name",
        "drill_name_raw",
        "attempt",
        "time",
        "frame",
        "t",
        "x",
        "y",
        "s",
        "a",
        "dis",
        "dis_raw",
        "dir",
        "quantized",
        "truncated_rep",
    ]
    player = player.select(
        [c for c in order if c in player.columns] + [c for c in player.columns if c not in order]
    )

    fast = player.filter(pl.col("s") > 13).height
    rep.check("combine: no player frame faster than 13 yd/s", fast == 0, f"{fast:,} frames")
    rep.note(
        "combine: rows",
        f"{player.height:,} PLAYER, {ball.height:,} BALL, "
        f"{player.select(keys).n_unique():,} attempts, {player['nfl_id'].n_unique()} players",
    )
    return _categorize(player), _categorize(ball)


def build_game_tracking(
    raw: Path, season: int, games: pl.DataFrame, plays: pl.DataFrame, rep: Report
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Returns (tracking frame, unique tracking keys) for one season file."""
    keys = ["game_id", "play_id", "nfl_id"]
    df = (
        pl.scan_csv(
            _find(raw, f"game_tracking_{season}"), schema_overrides=GAME_TYPES, null_values=NULLS
        )
        .with_columns(pl.col("time").str.to_datetime(TIME_FMT, strict=False))
        .collect()
    )
    directions = plays.select("game_id", "play_id", "play_direction").unique(["game_id", "play_id"])
    play_keys = plays.select(keys).with_columns(has_play_row=pl.lit(True))
    df = (
        df.join(games.select("game_id", "season", "season_type", "week"), on="game_id", how="left")
        .join(directions, on=["game_id", "play_id"], how="left")
        .join(play_keys, on=keys, how="left")
        .with_columns(pl.col("has_play_row").fill_null(False))
        .sort(*keys, "time")
    )
    snaps = (
        df.filter(pl.col("event").is_in(SNAP_EVENTS))
        .group_by("game_id", "play_id")
        .agg(snap_time=pl.col("time").min())
    )
    left, right = pl.col("play_direction") == "left", pl.col("play_direction") == "right"

    def flip(c: str, size: float) -> pl.Expr:
        return pl.when(left).then(size - pl.col(c)).when(right).then(pl.col(c)).cast(F32)

    def turn(c: str) -> pl.Expr:
        return pl.when(left).then((pl.col(c) + 180) % 360).when(right).then(pl.col(c)).cast(F32)

    df = (
        df.join(snaps, on=["game_id", "play_id"], how="left")
        .with_columns(
            frame=pl.int_range(pl.len(), dtype=I16).over(keys),
            t_since_snap=_seconds(pl.col("time") - pl.col("snap_time")),
            # standardised: offense always moves toward +x. Null when direction is unknown.
            x_std=flip("x", FIELD_LENGTH),
            y_std=flip("y", FIELD_WIDTH),
            o_std=turn("o"),
            dir_std=turn("dir"),
        )
        .drop("snap_time")
    )
    order = [
        "game_id",
        "play_id",
        "nfl_id",
        "season",
        "season_type",
        "week",
        "time",
        "frame",
        "t_since_snap",
        "event",
        "x_std",
        "y_std",
        "s",
        "a",
        "dis",
        "o_std",
        "dir_std",
        "x",
        "y",
        "o",
        "dir",
        "play_direction",
        "has_play_row",
    ]
    df = df.select(
        [c for c in order if c in df.columns] + [c for c in df.columns if c not in order]
    )

    tkeys = df.select(keys).unique()
    no_ctx = tkeys.join(play_keys, on=keys, how="anti").height
    no_snap = df.filter(pl.col("t_since_snap").is_null()).select(["game_id", "play_id"]).n_unique()
    no_dir = df.filter(pl.col("play_direction").is_null()).select(["game_id", "play_id"]).n_unique()
    rep.check(f"game_tracking_{season}: no unparsed timestamps", df["time"].null_count() == 0)
    rep.note(
        f"game_tracking_{season}: keys without player_play row",
        f"{no_ctx:,} of {tkeys.height:,} (host: plays killed by pre-snap penalty)",
    )
    rep.note(
        f"game_tracking_{season}: plays with no snap event / no direction",
        f"{no_snap:,} / {no_dir:,}",
    )
    return _categorize(df), tkeys


def build_players(raw: Path, plays: pl.DataFrame, combine: pl.DataFrame, rep: Report):
    players = _read_small(raw, "players")
    results = _read_small(raw, "combine_results")
    career = _read_small(raw, "player_career_successes")
    for df, label in [(players, "players"), (results, "combine_results"), (career, "career")]:
        _unique(df, ["nfl_id"], label, rep)

    mism = players.join(results.select("nfl_id", "draft_year"), on="nfl_id", suffix="_c").filter(
        pl.col("draft_year") != pl.col("draft_year_c")
    )
    rep.check("players vs combine_results: draft_year agrees", mism.height == 0, f"{mism.height}")

    df = players.join(results.drop("draft_year"), on="nfl_id", how="left").join(
        career, on="nfl_id", how="left"
    )
    seasons = (LAST_SEASON - pl.col("draft_year").cast(I32) + 1).cast(I16)
    combine_day = pl.date(pl.col("draft_year").cast(I32), 3, 1)
    derived: dict[str, pl.Expr] = {
        "is_udfa": pl.col("draft_round").is_null(),
        "seasons_available": seasons,
        "age_at_combine": ((combine_day - pl.col("birth_date")).dt.total_days() / 365.25).cast(F32),
        "bmi": (703 * pl.col("combine_weight") / pl.col("combine_height") ** 2).cast(F32),
        "speed_score": (pl.col("combine_weight") * 200 / pl.col("forty") ** 4).cast(F32),
        "career_scrimmage_snaps": pl.col("career_offensive_snaps")
        + pl.col("career_defensive_snaps"),
    }
    df = df.with_columns(**{k: v for k, v in derived.items() if _cols_ok(v, df)})
    df = df.with_columns(
        [pl.col(t).is_null().alias(f"opted_out_{t}") for t in COMBINE_TESTS if t in df.columns]
    )
    per_season = [
        "career_scrimmage_snaps",
        "career_special_teams_snaps",
        "career_games_active",
        "career_games_started",
    ]
    df = df.with_columns(
        [
            (pl.col(c) / pl.col("seasons_available"))
            .cast(F32)
            .alias(f"{c.removeprefix('career_')}_per_season")
            for c in per_season
            if c in df.columns
        ]
    )

    reg = plays.filter(pl.col("season_type") == "REG")
    play_counts = plays.group_by("nfl_id").agg(
        n_plays=pl.len(),
        n_plays_reg=pl.col("season_type").eq("REG").sum(),
        n_plays_reg_rookie=(pl.col("season_type").eq("REG") & pl.col("is_rookie_season")).sum(),
    )
    attempts = combine.group_by("nfl_id").agg(
        n_combine_attempts=pl.col("event_id").n_unique(),
        n_combine_drills=pl.col("drill_name").n_unique(),
    )
    df = (
        df.join(play_counts, on="nfl_id", how="left")
        .join(attempts, on="nfl_id", how="left")
        .with_columns(
            pl.col(
                "n_plays",
                "n_plays_reg",
                "n_plays_reg_rookie",
                "n_combine_attempts",
                "n_combine_drills",
            ).fill_null(0),
        )
        .with_columns(
            has_nfl_plays=pl.col("n_plays") > 0,
            has_combine_tracking=pl.col("n_combine_attempts") > 0,
        )
    )
    rep.note(
        "players",
        f"{df.height} prospects; {df['has_nfl_plays'].sum()} with plays "
        f"({reg['nfl_id'].n_unique()} with REG plays); "
        f"{df['has_combine_tracking'].sum()} with Combine tracking; {df['is_udfa'].sum()} UDFA",
    )
    return _categorize(df)


# --------------------------------------------------------------------------- driver
def build_all(raw: Path, out: Path, force: bool = False, hash_raw: bool = True) -> Report:
    out.mkdir(parents=True, exist_ok=True)
    manifest = out / "manifest.json"
    if manifest.exists() and not force:
        print(f"{manifest} exists: processed data is already built. Use --force to rebuild.")
        return Report()

    t0, rep = time.time(), Report()
    print("games / plays")
    games = build_games(raw, rep)
    draft_years = _read_small(raw, "players").select("nfl_id", "draft_year")
    plays = build_plays_base(raw, games, draft_years, rep)

    print("combine tracking")
    positions = _read_small(raw, "combine_results").select("nfl_id", "combine_position")
    combine, ball = build_combine_tracking(raw, positions, rep)
    _write(combine, out, "combine_tracking", rep)
    _write(ball, out, "combine_ball", rep)

    print("game tracking")
    tracked = []
    for season in SEASONS:
        gt, tkeys = build_game_tracking(raw, season, games, plays, rep)
        _write(gt, out, f"game_tracking_{season}", rep)
        tracked.append(tkeys)
        del gt
    tracked_keys = pl.concat(tracked).unique().with_columns(has_tracking=pl.lit(True))
    plays = plays.join(tracked_keys, on=["game_id", "play_id", "nfl_id"], how="left").with_columns(
        pl.col("has_tracking").fill_null(False)
    )
    no_trk = plays.filter(~pl.col("has_tracking")).height
    rep.note(
        "plays without tracking",
        f"{no_trk:,} of {plays.height:,} (host: WR/TE rows on plays they didn't run a route)",
    )

    print("players / write")
    players = build_players(raw, plays, combine, rep)
    _write(players, out, "players", rep)
    _write(_categorize(games), out, "games", rep)
    _write(_categorize(plays), out, "plays", rep)

    raw_files = sorted(raw.rglob("*.csv"))
    meta = {
        "built_at": dt.datetime.now().isoformat(timespec="seconds"),
        "seconds": round(time.time() - t0, 1),
        "polars": pl.__version__,
        "raw": {
            p.name: {"bytes": p.stat().st_size, **({"sha256": _sha256(p)} if hash_raw else {})}
            for p in raw_files
        },
        "outputs": rep.outputs,
        "checks": rep.checks,
        **rep.extra,
    }
    manifest.write_text(json.dumps(meta, indent=2, default=str))
    warns = sum(c["ok"] is False for c in rep.checks)
    print(f"\nDone in {meta['seconds']}s, {warns} warning(s). See {manifest}")
    return rep
