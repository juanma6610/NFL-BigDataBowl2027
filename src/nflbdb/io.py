"""Loaders for the processed BDB 2027 parquet (built by scripts/download_data.py).

Tables (data/processed/)
------------------------
players                 510 rows   nfl_id                  bio, draft, combine, career, derived
games                   1,002 rows game_id                 includes PRE and POST games
plays                   314k rows  game_id,play_id,nfl_id  player_play + game context + derived
combine_tracking        ~431k rows event_id,nfl_id,frame   10 Hz Combine drills, PLAYER rows only
combine_ball            ~32k rows  event_id,nfl_id,frame   Combine ball frames (WR/TE drills)
game_tracking_{season}  3.7M / 7.8M / 11.2M rows           10 Hz in-game, rookies only (no ball,
                                                           no opponents)

Nothing is filtered at build time. Preseason/postseason, truncated reps and plays killed
pre-snap are flagged (season_type, truncated_rep, pre_snap_dead, has_play_row, ...): choose
filters here, at load time. Everything returns lazy frames except players(); filter early.
"""

from collections.abc import Iterable
from pathlib import Path

import polars as pl

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "processed"
SEASONS = (2023, 2024, 2025)


def _path(name: str) -> Path:
    path = DATA_DIR / f"{name}.parquet"
    if not path.exists():
        available = ", ".join(sorted(p.stem for p in DATA_DIR.glob("*.parquet"))) or "none"
        raise FileNotFoundError(
            f"{path.name} not found in {DATA_DIR}. Available: {available}. "
            "Run `uv run python scripts/download_data.py` first."
        )
    return path


def _as_list(v: str | Iterable[str]) -> list[str]:
    return [v] if isinstance(v, str) else list(v)


def load(name: str) -> pl.LazyFrame:
    """Lazy-load any processed table by name, e.g. load("plays"). Call .collect() to materialise."""
    return pl.scan_parquet(_path(name))


def players() -> pl.DataFrame:
    """One row per prospect (510): players + combine_results + career + derived columns."""
    return load("players").collect()


player_cohort = players  # backwards-compatible name


def load_plays(regular_only: bool = False, live_only: bool = False) -> pl.LazyFrame:
    """Player-play rows. regular_only keeps REG games; live_only drops plays killed pre-snap."""
    lf = load("plays")
    if regular_only:
        lf = lf.filter(pl.col("season_type") == "REG")
    if live_only:
        lf = lf.filter(~pl.col("pre_snap_dead"))
    return lf


def load_combine_tracking(
    drill_type: str | Iterable[str] | None = None,
    drill_name: str | Iterable[str] | None = None,
    include_truncated: bool = True,
) -> pl.LazyFrame:
    """Combine drill tracking (PLAYER rows), with per-attempt `frame` and `t` (seconds).

    drill_type: e.g. "THREE_CONE_DRILL" or ["SKILL_DRILLS_WR", "SKILL_DRILLS_DB"].
    drill_name: normalised names, e.g. "PASS_PRO_MIRROR_DRILL".
    Use `dis` (recomputed from x/y), not `dis_raw`. Coordinates are the Combine frame,
    not a game field: don't apply game-field standardisation.
    """
    lf = load("combine_tracking")
    if drill_type is not None:
        lf = lf.filter(pl.col("drill_type").cast(pl.String).is_in(_as_list(drill_type)))
    if drill_name is not None:
        lf = lf.filter(pl.col("drill_name").cast(pl.String).is_in(_as_list(drill_name)))
    if not include_truncated:
        lf = lf.filter(~pl.col("truncated_rep"))
    return lf


def load_game_tracking(
    seasons: int | Iterable[int] = SEASONS,
    regular_only: bool = False,
    play_columns: Iterable[str] | None = None,
) -> pl.LazyFrame:
    """In-game tracking for the chosen season(s).

    Coordinates: x_std/y_std/o_std/dir_std are standardised so the offense moves toward +x
    (null where the play direction is unknown); raw x/y/o/dir are kept alongside.
    `t_since_snap` is seconds relative to the ball_snap event (negative = pre-snap).
    play_columns: extra columns to join from `plays`, e.g. ["route_ran", "pass_result"].
    ~22.6M rows across seasons: filter early (nfl_id / game_id) and stay lazy.
    """
    seasons = [seasons] if isinstance(seasons, int) else list(seasons)
    lf = pl.concat([load(f"game_tracking_{s}") for s in seasons], how="vertical_relaxed")
    if regular_only:
        lf = lf.filter(pl.col("season_type") == "REG")
    if play_columns:
        keys = ["game_id", "play_id", "nfl_id"]
        lf = lf.join(load("plays").select(*keys, *play_columns), on=keys, how="left")
    return lf
