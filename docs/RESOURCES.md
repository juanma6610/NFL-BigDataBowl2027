# NFL Big Data Bowl 2027: competition brief and resource map

*Compiled 2026-10-18, 12 days after launch. Kaggle notebook and discussion counts change daily.*

---

## 1. The competition in one page

**Theme: Combine to NFL performance.** Build an analytical framework that finds *non-obvious, actionable* links between **10 Hz Combine sensor tracking** and **future regular-season NFL game performance**. Kaggle: https://www.kaggle.com/competitions/nfl-big-data-bowl-2027

- **Format.** Analytics hackathon, with no leaderboard or metric to optimise. The host confirmed there will be no prediction track this year ([discussion/746521](https://www.kaggle.com/competitions/nfl-big-data-bowl-2027/discussion/746521)).
- **Deliverable.** A Kaggle Writeup with **≤ 2,000 words** and **< 10 tables/figures**, plus an attached **public Kaggle notebook**. The limits apply to the writeup only, not to an appendix or notebook ([746425](https://www.kaggle.com/competitions/nfl-big-data-bowl-2027/discussion/746425)). Each team gets one submission. Teams can have up to 5 people.
- **Pass/fail gates.** (1) The writeup explicitly links Combine **sensor tracking** to NFL game performance; (2) it is complete: readable markdown, embedded visuals and a public notebook. *A writeup that doesn't use the tracking data is not scored.*
- **Scoring rubric (0–10 per component). Judges are analytics staff from the 32 clubs and from tracking vendors.**
  | Component | Weight | What they ask |
  |---|---|---|
  | Football | 30% | Could a team use it week to week? Does it handle football's complexity? Is it unique? |
  | Data Science | 30% | Is it correct, backed by data, with appropriate models and an innovative application? |
  | Writeup | 20% | Is it well written and easy to follow, with a clearly defined motivation and metric? |
  | Data Viz | 20% | Are the charts accessible, accurate and innovative? |
- **Host guidance.** Focus narrowly on *one movement aspect, one position group, or one drill*. Their examples:
  - Route running and coverage: COD, decel into breaks and accel out of cuts, compared with **in-game separation**.
  - Trench play: first step, lateral agility and burst, compared with pass-rush or run-block outcomes.
  - Drill translation: sensor metrics compared with stopwatch times.
  - Position-specific mechanics: body control and pursuit angles.
- **Timeline.**
  | Date | Event |
  |---|---|
  | 2026-10-06 | Start |
  | **2027-01-06, 23:59 UTC** | **Deadline** |
  | 2027-01-07 to 2027-01-25 | Judging |
  | ~2027-01-26 | Results |
- **Prizes ($100k).**
  - Open track: 3 finalists × $10k and 3 runners-up × $5k.
  - University track (all-undergraduate teams): the same structure.
  - Grand prize: $10k, decided by a live presentation at the 2027 Scouting Combine in Indianapolis. Travel is paid. The presentation is in person only.
- **External data.** Allowed if it is public and free or minimal cost (Rules §6). LLM and AI assistants are allowed ([747086](https://www.kaggle.com/competitions/nfl-big-data-bowl-2027/discussion/747086)). Preseason and postseason outcomes may be used as supporting evidence ([746425](https://www.kaggle.com/competitions/nfl-big-data-bowl-2027/discussion/746425)).
- **Data licence.** CC BY-NC 4.0.

### Data (9 CSVs, about 2.2 GiB)
510 rookie prospects (2023–25 classes; 127 are UDFAs). Only **WR, TE, DB, OL and DL** have Combine tracking.
| File | Grain | Notes |
|---|---|---|
| players | nfl_id | draft round/pick, college, birth date |
| combine_results | nfl_id | 40, splits, jumps, agility, bench, arm/hand/wingspan, NGS athleticism/production/final scores |
| combine_tracking | event_id × nfl_id × time | 463,189 rows, 6,310 attempts; x,y,s,a,dis,dir (**no `o`**); PLAYER + BALL |
| player_career_successes | nfl_id | career snaps, games, starts, All-Pro, Pro Bowl |
| player_play | game_id, play_id, nfl_id | **314,197 rows** (not 316,338), 64 NGS columns: separation, cushion, get-off, time-to-pressure, pressure allowed, coverage… |
| games | game_id | 1,002 games, **includes PRE and POST** |
| game_tracking_{2023,2024,2025} | game, play, nfl_id, time | **3.67M / 7.83M / 11.16M rows (~22.6M total, not ~9M)**. **Rookie-cohort players only: no ball and no opponents** |

---

## 2. Data gotchas (sourced from host answers and audit notebooks)

These feed straight into your preprocessing step. The **(host)** label marks points confirmed by Tom Bliss, the NFL host.

1. **The Data tab's row counts were wrong. The CSVs are the full data** (host, [747584](https://www.kaggle.com/competitions/nfl-big-data-bowl-2027/discussion/747584)). Budget memory for about 22.6M game frames. The docstrings in `src/nflbdb/io.py` and `scripts/download_data.py` still say "~9M" and "316k".
2. **BALL rows carry the athlete's nfl_id** (host, [747108](https://www.kaggle.com/competitions/nfl-big-data-bowl-2027/discussion/747108)). Always filter `entity_type == "PLAYER"`. Only WR and TE drills have ball rows (54 players). The ball also causes "impossible" speeds: s up to 25.8 yd/s and 45-yd jumps.
3. **Combine `dis` is not the frame step.** It behaves like the squared step: it sums to about 36.7 yd over a 40. **Recompute distance from x/y.** The game files' `dis` is fine. Source: [dariushafshar audit](https://www.kaggle.com/code/dariushafshar/combine-tracking-audit-speed-r-0-95-start-r-0-28).
4. **The Combine coordinate frame is not a game field.** y can go negative (the 40 lane sits at y ≈ -0.5) and the 40 runs from x ≈ 10.7 to 51. Don't reuse old field-drawing code blindly. Source: [sigmatango EDA](https://www.kaggle.com/code/sigmatango/nfl-bdb-2027-complete-eda-data-quality-guide).
5. **The tracking window has no start signal.** The first frame is already moving at about 0.7 yd/s.
   - Tracked 10–40 split vs official: r ≈ 0.95.
   - Tracked first 10 yards vs official 10-yd split: r ≈ 0.28. **Starts and burst are unreliable, especially for WR and DB.**
   - Peak speed explains about 96% of 40 time.
6. **There are three data "vintages".**
   - 2023 uses Mongo-style event_ids with a `-2023` suffix. 2024–25 use timestamp ids.
   - 2023–24 coordinates and speeds are quantised to a grid; the sources disagree on whether it is 1/30 or 1/60 yd. 2025 is full precision.
   - **2024 BACK_PEDAL_AND_TRANSITION_45 reps are truncated before the break.** Treat them as missing, not near-zero.
   - → **Centre drill metrics by (drill, draft_year)** and fit that centring on training folds only. Source: [747105](https://www.kaggle.com/competitions/nfl-big-data-bowl-2027/discussion/747105).
7. **Some drill names are duplicates.** Normalise them before any group_by:
   - `PASS_PRO-MIRROR_DRILL` / `PASS_PRO_MIRROR_DRILL`
   - `OVER_SHOULDER_ADJUST` / `OVER_THE_SHOULDER_ADJUST`
   - `LINE_DRILL` / `LINE`
   - `SPEED_OUT_ROUTE_LEFT` / `SPEED_OUT_LEFT`
   - `SHORT_ZONE_BREAKS` appears under both the DL and LB drill types.

   `SKILL_DRILLS_LB` covers 4 players in 2023 only.
8. **Missing attempt numbers mean the data had an issue** and the attempt was dropped (host, [747187](https://www.kaggle.com/competitions/nfl-big-data-bowl-2027/discussion/747187)).
9. **PASS_RUSH_DRILL protocol** (host, [748656](https://www.kaggle.com/competitions/nfl-big-data-bowl-2027/discussion/748656)):
   - Dummies sit 4 yd from the centre, with a second set 4 yd behind; the finish cone is 7 yd behind the centre.
   - The left side uses a **rip**, the right side a **swim**. There is **no field that maps an attempt to rip or swim**.
   - The first and last frames are the drill start and end.
10. **WR and TE rows exist only on plays where they ran a route** (host, [748491](https://www.kaggle.com/competitions/nfl-big-data-bowl-2027/discussion/748491)). Blocking snaps are absent: coverage is about 58% of WR snaps and 40% of TE snaps.
11. **Tracking and player_play don't match perfectly** (host, [747108](https://www.kaggle.com/competitions/nfl-big-data-bowl-2027/discussion/747108)):
    - Tracking without player_play = a pre-snap penalty killed the play.
    - player_play without tracking = a WR or TE who didn't run a route.
    - The literal string `lined_up_position == "NA"` also means the play was killed pre-snap.
    - **13 players never reached the field.** That fact can itself be an outcome.
12. **No special-teams plays are in player_play**, though ST is about 17% of these players' snaps.
13. **Pass-rush fields** (host, [746678](https://www.kaggle.com/competitions/nfl-big-data-bowl-2027/discussion/746678)):
    - `blitzing == TRUE` means he rushed.
    - With `blitzing == TRUE`, a null time_to_pressure or quick_pressure means no pressure.
    - `quick_pressure == FALSE` means a pressure happened, but not a quick one.
    - A null `player_get_off` means he never crossed the LOS.
    - Dropbacks are plays with `pass_result != ""`.
14. **Filter `season_type == "REG"` for the main analysis.** Preseason is about 16% of tracked plays.
15. **Career totals measure exposure.** 2023 picks have had 3 seasons, 2025 picks 1. Normalise per season available, or compare within a class.
16. **Combine opt-outs are not random.** About 60% are missing 3-cone, shuttle or bench, and the rate varies by position. Don't just drop NAs.
17. **The real n is small.**
    - Only 243 players have a tracked 40 *and* at least 100 regular-season plays measuring their position's main outcome (TE 18 … DB 62).
    - A single test needs |r| ≈ 0.25–0.47. A multiple-comparison search needs |r| ≈ 0.36–0.68.
    - **Attempt-to-attempt reliability:**
      | Metric | Reliability |
      |---|---|
      | Top speed | r ≥ 0.89 |
      | Peak accel off the start, WR | 0.02 |
      | Peak accel off the start, DL | 0.65 |
      | WR and DB braking, drill to drill | ~0 |
    - Draft position absorbs most of the speed → playing-time signal. Pre-register hypotheses, report CIs, and control for size and draft slot.

---

## 3. Kaggle notebooks worth reading (2027)
Sorted roughly by votes. ★ marks the most useful.

**Data audits and starters**
- ★ [Combine Tracking Audit: Speed r=0.95, Start r=0.28](https://www.kaggle.com/code/dariushafshar/combine-tracking-audit-speed-r-0-95-start-r-0-28): reliability, noise floor, "test your own metric" scorecard, per-player metric CSV.
- ★ [Complete EDA & Data-Quality Guide](https://www.kaggle.com/code/sigmatango/nfl-bdb-2027-complete-eda-data-quality-guide): join map, drill catalogue, vintages, polars lazy loading.
- ★ [DB Drills Decoded: CB/S Tracking + 2024 Data Trap](https://www.kaggle.com/code/yumekohata/db-drills-decoded-cb-s-tracking-2024-data-trap)
- [BDB27 Join and Leakage Audit Kit](https://www.kaggle.com/code/yangkuangou/bdb27-join-and-leakage-audit-kit)
- [NFL BDB 2027 Starter: Combine to NFL](https://www.kaggle.com/code/nathanjacob/nfl-bdb-2027-starter-combine-to-nfl)
- [BDB27 EDA: Combine Tracking Meets NFL Tracking](https://www.kaggle.com/code/starkhushi/bdb27-eda-combine-tracking-meets-nfl-tracking)
- [NFL BDB 2027 Visual-Guide](https://www.kaggle.com/code/chovyxu/nfl-bdb-2027-visual-guide)
- [NFL Big Data Bowl 2027 (mpwolke)](https://www.kaggle.com/code/mpwolke/nfl-big-data-bowl-2027): the most-voted notebook, general EDA.
- [Measure Twice: Combine Tracking Reliability](https://www.kaggle.com/code/sainihim/measure-twice-combine-tracking-reliability)
- [Gauntlet Repeatability and NFL Value](https://www.kaggle.com/code/vaibhavpatel/gauntlet-repeatability-and-nfl-value)
- [40-Yard Dash vs 85-Yard TD | Animate Any Rookie](https://www.kaggle.com/code/busyaprime/40-yard-dash-vs-85-yard-td-animate-any-rookie): animation code.

**Outcome framing**
- ★ [Who Beat Their Combine? 2023-25 Rookies](https://www.kaggle.com/code/dariushafshar/who-beat-their-combine-2023-25-rookies): Combine adds ~0 beyond draft slot for playing time.
- [Indy or Tape? Pricing a Combine Workout](https://www.kaggle.com/code/olsols4/indy-or-tape-pricing-a-combine-workout)
- [Worth 44 Snaps: When Film Beats the Combine](https://www.kaggle.com/code/jasonrobinson1/worth-44-snaps-when-film-beats-the-combine)

**WR and DB: route running, COD and separation**
- [Wide Receivers Over-Braking Trap](https://www.kaggle.com/code/haydonnazar/wide-receivers-over-braking-trap-nfl)
- [Combine to Sunday: Same WR, Drill vs NFL Route](https://www.kaggle.com/code/sachith7/combine-to-sunday-same-wr-drill-vs-nfl-route)
- [Combine Route-Running Predicts NFL Separation](https://www.kaggle.com/code/zikuanqi/combine-route-running-predicts-nfl-separation)
- [Don't Grade an Unobserved Cut](https://www.kaggle.com/code/jeovaanderson/don-t-grade-an-unobserved-cut-bdb-2027)
- [Cut Recovery and Rookie Separation](https://www.kaggle.com/code/iatchenghuang/nfl-2027-cut-recovery-and-rookie-separation)
- [When Should Turning Data Change a WR Evaluation?](https://www.kaggle.com/code/hongjie04/when-should-turning-data-change-a-wr-evaluation)

**Trenches: DL and edge bend/burst, OL pass protection**
- [Bend Before Sacks: DL Combine Tracking](https://www.kaggle.com/code/agileteam/bend-before-sacks-dl-combine-tracking)
- [Curved Burst Efficiency for EDGE](https://www.kaggle.com/code/chadlite77/curved-burst-efficiency-for-nfl-edge-prospects)
- [Bending the Edge: 10 Hz Pass Rush Kinematics](https://www.kaggle.com/code/fercampoflorensa/bending-the-edge-10-hz-pass-rush-kinematics)
- [The Two-Yard Clock: Timing 26,623 Pass Rushes](https://www.kaggle.com/code/busyaprime/the-two-yard-clock-timing-26-623-pass-rushes)
- [Beyond the 40: OL Pass Protection](https://www.kaggle.com/code/nathanjacob/nfl-bdb-2027-beyond-the-40-ol-pass-protection)
- [Relative Mirror Recovery and Rookie Protection](https://www.kaggle.com/code/abhishekd2512/relative-mirror-recovery-and-rookie-protection)
- [OL Wave Drill Pass Pro Pressure](https://www.kaggle.com/code/aymenmouelhi/ol-wave-drill-pass-pro-pressure)
- [Rookie vs Rookie: Combine Traits in Trench Reps](https://www.kaggle.com/code/nateshingleton/rookie-vs-rookie-combine-traits-in-trench-reps) and [who-faced-whom matchup](https://www.kaggle.com/code/rolandobouloy/who-faced-whom-rookie-vs-rookie-matchup-bdb-2027): rookie-on-rookie plays put opponents back into the tracking.

Full list: https://www.kaggle.com/competitions/nfl-big-data-bowl-2027/code?sortBy=voteCount

**Saturated angles** (many near-duplicates): "beyond the stopwatch", generic "bend/burst" and cut-braking indices. Novelty is 30% of the Football score, so differentiate.

---

## 4. External data (allowed if public and free; keyed on nfl_id where possible)
- ★ **[BDB 2027 Public Enrichment](https://www.kaggle.com/datasets/dariushafshar/bdb-2027-public-enrichment)** (CC BY-SA). Contents:
  - nfl_id crosswalk to GSIS, PFR, PFF, OTC, ESPN and other ids.
  - Per-season snaps (offence, defence, ST) and team snaps, for snap share.
  - Games started, roster status, injury-report weeks and box scores for all 2023–25 rookies.
  - Includes the build and validate scripts.
- ★ **[nflreadpy](https://github.com/nflverse/nflreadpy)** (`uv add nflreadpy`; returns Polars). Useful loaders:
  - `load_players` (has nfl_id / gsis_id), `load_snap_counts`, `load_nextgen_stats`
  - `load_pbp` + `load_participation`, `load_ftn_charting`
  - `load_draft_picks`, `load_combine`, `load_contracts`, `load_injuries`, `load_depth_charts`, `load_rosters_weekly`

  R equivalent: [nflreadr](https://nflreadr.nflverse.com). Raw files: [nflverse-data releases](https://github.com/nflverse/nflverse-data/releases).
- **[Grinding the Mocks EDP snapshots](https://grindingthemocks.substack.com/p/grinding-the-mocks-provides-public)**: expected draft position at 5 points around the Combine, with nfl_id. Covers about 80% of the cohort. It measures how much the *market* reacted to the workout. Kaggle mirror: [jasonwold/grinding-the-mocks-bdb-2027-edp-combine-snaps](https://www.kaggle.com/datasets/jasonwold/grinding-the-mocks-bdb-2027-edp-combine-snaps); forum PSA [750297](https://www.kaggle.com/competitions/nfl-big-data-bowl-2027/discussion/750297).
- [nflverse features for BDB 2027](https://www.kaggle.com/datasets/kennedydot2004/nflverse-bdb-2027-ext): pre_/role_/out_ feature build script.
- [Pre-Draft College Features](https://www.kaggle.com/datasets/angelojun2k/nfl-bdb2027-predraft-college-features): conference tier and SOS-adjusted production. Check its provenance before using it.
- [nflverse Rosters/Injuries/Depth 2023-2025](https://www.kaggle.com/datasets/anshengjhang/nflverse-rosters-injuries-depth-2023-2025)
- Contracts and APY (OTC via nflreadpy) can serve as a "value" outcome. Relative Athletic Score (RAS) is a baseline to beat ([explainer](https://www.nbcsportsboston.com/nfl/new-england-patriots/what-is-ras-everything-you-need-to-know-about-the-draft-metric/293753)).
- Drill videos (from the host): [1](https://www.youtube.com/watch?v=a3WZJlkg6_k), [2](https://www.youtube.com/watch?v=BXsS5p4ySgc)

---

## 5. Libraries for tracking data
| Library | Lang | Use |
|---|---|---|
| [nflreadpy](https://github.com/nflverse/nflreadpy) | Py | nflverse data (Polars) |
| [unravelsports](https://unravelsports.readthedocs.io/en/stable/tutorials/american_football.html) | Py | BDB loader (Polars) → graphs → GNNs (PyG / Spektral) |
| [ptplot](https://github.com/AndrewRook/ptplot) | Py | Plotly field plots and animations of tracking data |
| [nfl-tracks](https://pypi.org/project/nfl-tracks) | Py | BDB tracking plotting and animation |
| [sportypy](https://github.com/sportsdataverse/sportypy) / [sportyR](https://cran.rstudio.com/web/packages/sportyR/vignettes/animating-tracking-data.html) | Py/R | Scaled field drawings and animation |
| [ngscleanR](https://github.com/guga31bb/ngscleanR) | R | Classic BDB cleaning (standardise direction, etc.); good reference logic |
| [ngs_highlights](https://github.com/asonty/ngs_highlights) | R | Public NGS highlight tracking |
| scipy.signal (Savitzky–Golay), filterpy (Kalman) | Py | Smooth x/y before differentiating to get accel, jerk and curvature |
| statsmodels / PyMC / bambi | Py | Mixed models (player random effects), reliability (ICC), Bayesian shrinkage |

Your stack (polars, sklearn, lightgbm, plotly) already covers most needs. Add `nflreadpy`, `scipy` and `statsmodels`, plus optionally `pingouin` for ICC.

---

## 6. Past Big Data Bowls (style and methods to borrow)
- **2026 (player movement while the ball is in the air).**
  - Grand prize: [Ghostbusters: Back off man, I'm a Data Scientist!](https://www.kaggle.com/competitions/nfl-big-data-bowl-2026-analytics/writeups/ghostbusters-back-off-man-im-a-data-scientist) by Lucca Ferraz (Rice). It evaluates defender movement against hypothetical "ghost" defender distributions, a counterfactual-baseline idea that transfers well to "expected vs actual movement".
  - Other finalists: [Visualizing Contested Space](https://www.kaggle.com/competitions/nfl-big-data-bowl-2026-analytics/writeups/new-writeup-1763346815984), [Path Against The Pass](https://www.kaggle.com/competitions/nfl-big-data-bowl-2026-analytics/writeups/new-writeup-1765813974702), [The Decision Point](https://www.kaggle.com/competitions/nfl-big-data-bowl-2026-analytics/writeups/the-decision-point), [Dynamic Completion Probability](https://www.kaggle.com/competitions/nfl-big-data-bowl-2026-analytics/writeups/new-writeup-1766008515218).
  - Winners page: https://www.kaggle.com/competitions/nfl-big-data-bowl-2026-analytics/hackathon-winners
- **2024 (tackling).** Winner: "Uncovering Missed Tackle Opportunities" ([code](https://github.com/mpchang/uncovering-missed-tackle-opportunities)).
- Hub for all years: https://operations.nfl.com/gameday/analytics/big-data-bowl. Original homepage repo: https://github.com/nfl-football-ops/Big-Data-Bowl
- **Judge-style critique.** [Thoughts on Big Data Bowl 2025](https://statthinksportsanalytics.substack.com/p/thoughts-on-big-data-bowl-2025) (Quang Nguyen):
  - Report base rates.
  - Beat a simple baseline.
  - Show uncertainty.
  - Remember that the sample is small and non-independent.
  - Novelty lies in the downstream use, not in accuracy.

---

## 7. Methods and literature
- [Here Comes the STRAIN](https://arxiv.org/abs/2305.10262): pass-rush metric from tracking. Directly relevant to DL burst → pressure.
- [NFL Ghosts](https://arxiv.org/abs/2406.17220): conditional density estimation of where a defender "should" be.
- [Bayesian circular mixed-effects model for directional movement](https://arxiv.org/abs/2507.06122): modelling `dir` properly with circular stats.
- [Feeling the Pressure (Amazon/NGS)](https://cdn.amazon.science/2b/fe/e4f2f6bc4092bba17cb3f84a0929/feeling-the-pressure-a-unified-framework-for-automating-pass-rushing-statistics-in-nfl-games.pdf): how NGS defines pressure and get-off (the source of the player_play fields).
- [The Deceleration Deficit](https://pureportal.bcu.ac.uk/en/publications/the-deceleration-deficit-a-novel-field-based-method-to-quantify-d/fingerprints/): sport-science framing for COD and braking metrics.
- [Tracking metrics and ACL risk in NFL change of direction](https://www.ebsco.com/articles/sports-and-leisure/83c00dad-fb37-56e7-9ec0-a00ee4f771f7/player-tracking-metrics-to-predict-risk-of-anterior-cruciate-ligament-injuries-during-change-of-direction-scenarios-in-the-national-football-league)
- Combine → NFL success, the classic weak-signal literature:
  - [Kuzmits & Adams 2008](https://ngdc.cncb.ac.cn/openlb/publication/OLB-PM-18841077)
  - [URI: Combine scores as performance predictors](https://digitalcommons.uri.edu/kinesiology_facpubs/89)
  - [Combine vs 5-year game performance](https://lida.sport-iat.de/ta/Record/4064265?lng=en)
  - [Berkeley SA: how important is the Combine?](https://ocf.berkeley.edu/~sportsanalytics/articles/nfl-combine.html)
- NGS "Combine IQ" and the athleticism/production scores in combine_results: [AP coverage](https://www.nbclosangeles.com/news/sports/nfl/nfl-nextgen-stats-team-new-tool-combine-results/3642262/)

---

## 8. Implications for the preprocessing and enrichment step
1. Keep raw → typed parquet as it is now. Add a **clean layer**:
   - Combine: PLAYER-only rows; normalised `drill_name`; `dis` recomputed from x/y; a per-attempt `frame` and `t` (seconds since first frame); a `vintage` flag; a flag for truncated 2024 back-pedal reps.
   - Game: `season`, `season_type` and `week` joined from games, plus the player_play context columns you need. Keep it lazy; 22.6M rows.
2. Add a **players master** at one row per nfl_id:
   - players + combine_results + career.
   - `seasons_available` = 2025 − draft_year + 1, and per-season rates.
   - `combine_position` vs `nfl_position`.
   - opt-out flags.
   - Optional external columns: snap share (Public Enrichment), EDP (Grinding the Mocks), RAS.
3. Add **feature tables**:
   - `combine_attempt_features`: one row per event_id × nfl_id (top speed, flying splits, peak decel, turn times, path curvature…).
   - `combine_player_features`: best and mean attempts, plus a reliability flag.
   - `play_features`: per player-play (max speed, get-off, separation, time-to-pressure…).
   - `player_season_outcomes`: REG only, aggregated per player-season.
4. Ship **join audits as tests**. The key (game_id, play_id, nfl_id) is unique in player_play; report unmatched counts rather than silently dropping rows.
5. **Standardise play direction** for game tracking (already in `io.py`). The Combine frame is different, so don't apply the same flip there.
