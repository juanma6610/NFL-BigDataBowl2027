# NFL-BigDataBowl2027
NFL Big Data Bowl 2027: linking 10 Hz Combine tracking to NFL game performance.
Competition notes and resources: [docs/RESOURCES.md](docs/RESOURCES.md).

## Data pipeline

```bash
uv sync
uv run python scripts/download_data.py                  # download to data/raw, build data/processed
uv run python scripts/download_data.py --skip-download --force   # rebuild from raw
```

Needs a Kaggle API token (`~/.kaggle/kaggle.json` or `KAGGLE_USERNAME`/`KAGGLE_KEY` in `.env`)
and the competition rules accepted on Kaggle. Peak RAM is about 4 GB.

`data/raw/` holds the CSVs exactly as downloaded. `data/processed/` holds the cleaned parquet
built by `src/nflbdb/build.py`:

| table | grain | notes |
|---|---|---|
| `players` | nfl_id | bio, draft, combine results, career + derived (age, BMI, speed score, opt-outs, per-season rates, play counts) |
| `games` | game_id | includes PRE and POST |
| `plays` | game_id, play_id, nfl_id | player_play + game context + situation (score diff, yardline_100, time left, rookie season, has_tracking) |
| `combine_tracking` | event_id, nfl_id, frame | PLAYER rows only, drill names normalised, `dis` recomputed from x/y, `t`, `truncated_rep` |
| `combine_ball` | event_id, nfl_id, frame | ball frames from WR/TE drills |
| `game_tracking_{season}` | game_id, play_id, nfl_id, frame | standardised `x_std/y_std/o_std/dir_std`, `t_since_snap`, `has_play_row` |
| `manifest.json` | | raw file hashes, row counts, data checks, drill-name catalogue |

Nothing is filtered at build time: preseason, truncated reps and plays killed pre-snap are
flagged, and you choose filters when loading:

```python
from nflbdb import players, load_plays, load_combine_tracking, load_game_tracking

p = players()
plays = load_plays(regular_only=True, live_only=True)
cones = load_combine_tracking("THREE_CONE_DRILL")
wr = load_game_tracking(2024, regular_only=True, play_columns=["route_ran"])
```
