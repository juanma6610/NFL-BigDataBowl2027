"""Download the BDB 2027 data into data/raw, then build cleaned parquet into data/processed.

Usage:
    uv run python scripts/download_data.py                  # download (if needed) + build
    uv run python scripts/download_data.py <slug>           # override the competition slug
    uv run python scripts/download_data.py --skip-download  # build from existing data/raw
    uv run python scripts/download_data.py --force          # rebuild even if already built
    uv run python scripts/download_data.py --no-hash        # skip sha256 of raw CSVs (faster)

Raw CSVs (~2.2 GiB) are never modified. See src/nflbdb/build.py for what the build does and
data/processed/manifest.json (written at the end) for row counts and data checks.
Needs ~4-5 GB of free RAM: each game-tracking season (up to ~11M rows) is built in memory.
"""

import os
import sys
import zipfile
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from nflbdb.build import build_all  # noqa: E402

RAW = ROOT / "data" / "raw"
PROC = ROOT / "data" / "processed"


def download(slug: str) -> None:
    if any(RAW.rglob("*.csv")):
        print(f"CSVs already in {RAW}, skipping download (delete them to re-download).")
        return
    from kaggle.api.kaggle_api_extended import KaggleApi  # needs ~/.kaggle/kaggle.json or env

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


def main() -> None:
    load_dotenv(ROOT / ".env")
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--skip-download" not in sys.argv:
        download(args[0] if args else os.getenv("COMPETITION", "nfl-big-data-bowl-2027"))
    build_all(RAW, PROC, force="--force" in sys.argv, hash_raw="--no-hash" not in sys.argv)


if __name__ == "__main__":
    main()
