"""Download the BDB 2027 data into data/raw, then convert every CSV to typed parquet.

Usage:
    uv run python scripts/download_data.py              # uses COMPETITION from .env
    uv run python scripts/download_data.py <slug>       # override
    uv run python scripts/download_data.py --convert-only   # skip download, just (re)convert

Expected files (~2.2 GiB CSV -> roughly 4-6x smaller as parquet):
    players, combine_results, combine_tracking, player_career_successes,
    player_play, games, game_tracking_2023/2024/2025
"""

import os
import sys
import zipfile
from pathlib import Path

import polars as pl
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
PROC = ROOT / "data" / "processed"

NULLS = ["NA", "NULL", "null", "None", ""]
TIME_FMT = "%Y-%m-%dT%H:%M:%S%.f"

# Explicit schemas for the big tracking files: no inference pass over ~2 GiB,
# and no surprises from columns that are null for the first N rows.
F64, I64, STR = pl.Float64, pl.Int64, pl.String
SCHEMAS: dict[str, dict[str, pl.DataType]] = {
    "combine_tracking": {
        "draft_year": I64, "event_id": STR, "nfl_id": I64, "entity_type": STR, "time": STR,
        "drill_type": STR, "drill_name": STR, "attempt": I64,
        "x": F64, "y": F64, "s": F64, "a": F64, "dis": F64, "dir": F64,
    },
    "game_tracking": {
        "game_id": I64, "play_id": I64, "nfl_id": I64, "time": STR,
        "x": F64, "y": F64, "s": F64, "a": F64, "dis": F64, "o": F64, "dir": F64, "event": STR,
    },
}  # fmt: skip

# Read some numeric-looking ids as strings (event_id is a long digit string)
OVERRIDES: dict[str, dict[str, pl.DataType]] = {"combine_tracking": {"event_id": STR}}


def download(slug: str) -> None:
    from kaggle.api.kaggle_api_extended import KaggleApi  # needs ~/.kaggle/kaggle.json

    api = KaggleApi()
    api.authenticate()
    RAW.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {slug} -> {RAW}  (~2.2 GiB, takes a while)")
    try:
        api.competition_download_files(slug, path=str(RAW), quiet=False)
    except Exception as e:  # noqa: BLE001
        if "403" in str(e):
            sys.exit(
                "403 Forbidden: open the competition page on Kaggle and click "
                "'Join Hackathon' / accept the rules first."
            )
        raise
    for z in RAW.glob("*.zip"):
        print(f"Unzipping {z.name}")
        with zipfile.ZipFile(z) as zf:
            zf.extractall(RAW)
        z.unlink()


def _fix_types(lf: pl.LazyFrame) -> pl.LazyFrame:
    """Parse ISO timestamps and 'True'/'False' string columns."""
    schema = lf.collect_schema()
    exprs = []
    if schema.get("time") == pl.String:
        exprs.append(pl.col("time").str.to_datetime(TIME_FMT, strict=False))
    if schema.get("birth_date") == pl.String:
        exprs.append(pl.col("birth_date").str.to_date("%Y-%m-%d", strict=False))
    if exprs:
        lf = lf.with_columns(exprs)
    return lf


def _cast_bool_strings(df: pl.DataFrame) -> pl.DataFrame:
    """Small tables only: turn columns whose values are all True/False/null into Boolean."""
    casts = []
    for name, dtype in df.schema.items():
        if dtype == pl.String:
            vals = set(df[name].drop_nulls().unique().str.to_lowercase().to_list())
            if vals and vals <= {"true", "false"}:
                casts.append(pl.col(name).str.to_lowercase().eq("true").alias(name))
    return df.with_columns(casts) if casts else df


def convert() -> None:
    PROC.mkdir(parents=True, exist_ok=True)
    csvs = sorted(RAW.rglob("*.csv"))
    if not csvs:
        sys.exit(f"No CSVs in {RAW}. Run without --convert-only first.")
    for csv in csvs:
        out = PROC / f"{csv.stem}.parquet"
        if out.exists():
            print(f"skip  {out.name} (exists)")
            continue
        key = "game_tracking" if csv.stem.startswith("game_tracking") else csv.stem
        print(f"conv  {csv.name} -> {out.name}")
        if key in SCHEMAS:
            lf = pl.scan_csv(csv, schema=SCHEMAS[key], null_values=NULLS)
            _fix_types(lf).sink_parquet(out, compression="zstd")
        else:
            # <150 MB: read fully with full-file schema inference for correct dtypes
            df = pl.read_csv(
                csv,
                infer_schema_length=None,
                null_values=NULLS,
                schema_overrides=OVERRIDES.get(key),
            )
            df = _cast_bool_strings(_fix_types(df.lazy()).collect())
            df.write_parquet(out, compression="zstd")

    print("\nDone:")
    for f in sorted(PROC.glob("*.parquet")):
        n = pl.scan_parquet(f).select(pl.len()).collect().item()
        print(f"  {f.name:32s} {n:>12,} rows  {f.stat().st_size / 2**20:8.1f} MiB")


def main() -> None:
    load_dotenv(ROOT / ".env")
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--convert-only" not in sys.argv:
        slug = args[0] if args else os.getenv("COMPETITION", "nfl-big-data-bowl-2027")
        download(slug)
    convert()


if __name__ == "__main__":
    main()
