"""Loaders for the NFL Big Data Bowl 2027 data (parquet produced by scripts/download_data.py).

Tables
------
players                 510 rows   nfl_id            draft info, position, college
combine_results         510 rows   nfl_id            40, shuttle, 3-cone, jumps, NGS scores
player_career_successes 510 rows   nfl_id            snaps, games, starts, All-Pro, Pro Bowl
combine_tracking        463k rows  event_id,nfl_id   10 Hz Combine drills (no `o` column)
games                   1,002 rows game_id
player_play             316k rows  game_id,play_id,nfl_id   per-snap NGS metrics, play_direction
game_tracking_{season}  ~9M rows   game_id,play_id,nfl_id,time   10 Hz in-game, rookies only
"""

from collections.abc import Iterable
from pathlib import Path

import polars as pl

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "processed"
SEASONS = (2023, 2024, 2025)
FIELD_LENGTH, FIELD_WIDTH = 120.0, 53.3


def _path(name: str) -> Path:
    path = DATA_DIR / f"{name}.parquet"
    if not path.exists():
        available = ", ".join(sorted(p.stem for p in DATA_DIR.glob("*.parquet"))) or "none"
        raise FileNotFoundError(
            f"{path.name} not found in {DATA_DIR}. Available: {available}. "
            "Run `uv run python scripts/download_data.py` first."
        )
    return path


def load(name: str) -> pl.LazyFrame:
    """Lazy-load any table by name, e.g. load("players"). Call .collect() to materialise."""
    return pl.scan_parquet(_path(name))


def player_cohort() -> pl.DataFrame:
    """One row per prospect: players + combine_results + player_career_successes."""
    return (
        load("players")
        .join(load("combine_results").drop("draft_year"), on="nfl_id", how="left")
        .join(load("player_career_successes"), on="nfl_id", how="left")
        .collect()
    )


def load_combine_tracking(
    drill_type: str | Iterable[str] | None = None, players_only: bool = True
) -> pl.LazyFrame:
    """Combine drill tracking with a per-attempt `frame` index (0, 1, 2, ... at 10 Hz).

    drill_type: e.g. "THREE_CONE_DRILL" or ["SKILL_DRILLS_WR", "SKILL_DRILLS_DB"].
    """
    lf = load("combine_tracking")
    if players_only:
        lf = lf.filter(pl.col("entity_type") == "PLAYER")
    if drill_type is not None:
        types = [drill_type] if isinstance(drill_type, str) else list(drill_type)
        lf = lf.filter(pl.col("drill_type").is_in(types))
    return lf.sort("event_id", "nfl_id", "time").with_columns(
        frame=pl.int_range(pl.len()).over("event_id", "nfl_id")
    )


def load_game_tracking(
    seasons: int | Iterable[int] = SEASONS, standardize: bool = True
) -> pl.LazyFrame:
    """In-game tracking for the chosen season(s), with `season` and a per-play `frame` index.

    standardize=True joins `play_direction` from player_play and flips plays so the
    offense always moves toward +x (x -> 120-x, y -> 53.3-y, angles +180).
    Tracking is ~9M rows across seasons: filter early (by nfl_id / game_id) and stay lazy.
    """
    seasons = [seasons] if isinstance(seasons, int) else list(seasons)
    lf = pl.concat(
        [
            pl.scan_parquet(_path(f"game_tracking_{s}")).with_columns(season=pl.lit(s))
            for s in seasons
        ]
    )
    lf = lf.sort("game_id", "play_id", "nfl_id", "time").with_columns(
        frame=pl.int_range(pl.len()).over("game_id", "play_id", "nfl_id")
    )
    if standardize:
        directions = load("player_play").select("game_id", "play_id", "play_direction").unique()
        lf = standardize_direction(lf.join(directions, on=["game_id", "play_id"], how="left"))
    return lf


def standardize_direction(lf: pl.LazyFrame, dir_col: str = "play_direction") -> pl.LazyFrame:
    """Flip plays moving left so offense always moves toward +x."""
    cols = lf.collect_schema().names()
    left = pl.col(dir_col) == "left"
    exprs = [
        pl.when(left).then(FIELD_LENGTH - pl.col("x")).otherwise(pl.col("x")).alias("x"),
        pl.when(left).then(FIELD_WIDTH - pl.col("y")).otherwise(pl.col("y")).alias("y"),
    ]
    for angle in ("o", "dir"):
        if angle in cols:
            exprs.append(
                pl.when(left)
                .then((pl.col(angle) + 180) % 360)
                .otherwise(pl.col(angle))
                .alias(angle)
            )
    return lf.with_columns(exprs)
