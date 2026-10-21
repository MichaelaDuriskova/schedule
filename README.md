# QUVIK orbital scheduler

Schedules satellite observations into orbital eclipse passes (~35 min of
umbra per ~94 min orbit). Targets and observation requests live in a small
Django app; the scheduler builds visibility windows from the mission TLE
and solves the packing problem with CP-SAT (Google OR-Tools).

## Layout

| path | role |
|---|---|
| `sched_first.py` | main entry point: one run = one schedule "line" |
| `sched_zeros.py` | simplified/older standalone variant of `sched_first.py` (no chunking, cofield, verify gate or vis_cache) -- purpose/status to be confirmed |
| `orbital_scheduler.py` | adapter: objectives → chunk reservations, slew model, co-field grouping, remainder bookkeeping |
| `kernel/` | time-sliced CP-SAT solver (`solver.py`) plus shared `intervals`/`reservation`/`scheduler_base` |
| `visibility_loop.py` | sgp4 eclipse + Earth-limb visibility sampling (parallel per eclipse) |
| `vis_cache.py` | coverage-aware visibility cache: TLE-stamped, recomputes only missing periods/targets, wired into `sched_first.py` via `attach_cache()` |
| `verify_schedule.py` | independent post-run gate (umbra, limb, sun/moon, slew); exposures that fail a per-target check are dropped and the rest still saved, a genuine pairwise slew/overlap conflict blocks the whole save |
| `check_candidates.py` | read-only diagnostic: for every unscheduled campaign candidate, reports whether it has a usable visibility window and why not (sun/moon/earth-limb) |
| `export_schedule.py` | human-readable per-orbit listing + loadable SQL for one line |
| `colibri_import.py` | pull recent transients from Astro-COLIBRI as objectives |
| `fill_infield.py` | populate `Target.infield`/`nearby` from catalog geometry |
| `hermes_import.py` | pull GCN circulars via the HERMES API -- currently incomplete (missing `django.setup()`/`Target` import, its `make_target()` helper is unused) |
| `mockat/` | Django app: `Target`, `Objective` (what to observe), `Schedule` (one planned exposure); web views include a per-line schedule page, a yearly heatmap, a per-day listing, and an objective browser |
| `trigger/` | Django app: Fermi GBM / GCN notice ingestion |
| `sqlite_open.ipynb` | notebook for browsing/editing the DB directly (raw sqlite3 + pandas): list groups, tag objectives into a campaign, create objectives by group, set target priority, clear a schedule line's bookkeeping |
| `db.sqlite3` | targets, objectives, schedules (not committed -- see `.gitignore`; each environment keeps its own) |

## Quickstart

Python 3 with `django astropy sgp4 scipy numpy ortools plotly requests`
(see `requirements.txt`).

```bash
python sched_first.py --date 2026-09-26T00:00:00 --delta 45000 \
    --sched-line 60 --vis-file viscache.npz --slew-penalty-weight 1.0

python export_schedule.py --line 60 --vis-file viscache.npz   # -> line60_schedule.{txt,sql}
```

A run: selects objectives (`--camp` prefix, default `schedme`), ensures the
visibility cache covers the window via `vis_cache.VisibilityCache` (ensures
only what's missing, both target-set and time-range aware -- extending
`--delta` alone no longer silently reuses a too-short cache), solves,
**verifies independently**, saves the line, prints it. Re-running the same
`--sched-line` regenerates it cleanly (bookkeeping is rolled back first).
Useful knobs: `--max-chunk` / `--free-split` (exposure splitting),
`--cofield-radius` (multi-target pointings), `--remainder-boost`,
`--eclipse-margin`, `--sun-limit` (Sun avoidance, both the coarse
pre-filter and the scheduler's own constraint), `--slice` (grid
granularity). See `--help`.

## Concepts

- **Eclipse-only observing** — observations outside the umbra are excluded
  automatically: visibility exists only inside eclipse windows (trimmed by
  `--eclipse-margin` at both edges), so nothing can be scheduled in
  sunlight, and the independent verification gate re-checks every exposure
  against its own shadow model before the line is saved.
- **Chunks & remainders** — an objective's total exposure is split into
  schedulable chunks (up to `--max-chunk` seconds each); totals accumulate
  across passes and lines. Progress is tracked in
  `Objective.notes['done_by_line']`; `scheduled_line` is stamped only when
  the total is reached, so partially observed objectives stay eligible
  (with a `--remainder-boost` priority bump) in later lines.
- **Cadence** — `delay > 0` on an Objective disables chunking entirely: its
  whole total (`expo*repeat + delay*(repeat-1)`) becomes one continuous
  reservation, so it must fit inside a single eclipse pass or it can never
  be scheduled. Use `delay=0` for anything whose total needs to span
  multiple passes.
- **Slew model** — 60 s settle + trapezoidal transit (`2·√(d/a)` below
  ~104°); enforced as hard pairwise constraints, with an optional
  adjacency bonus (`--slew-penalty-weight`) that favors grouping
  angularly close targets within a pass.
- **Co-field** — targets within `--cofield-radius` of a pointing's primary
  are exposed simultaneously and all credited (FoV 0.9°×0.5°; 0.25°
  is roll-safe).
- **Visibility cache** — `VisibilityCache(path, tle).ensure(t0, t1, pks)`
  knows its TLE, its covered time segments, and which targets each eclipse
  period was sampled with; it recomputes only the missing pieces, always
  through the parallel fill. A TLE change invalidates it; legacy
  (unstamped) cache files are treated as stale unless `trust_legacy=True`.
  Two caches built for the same TLE can be combined with `+`/`+=`
  (`VisibilityCache.merge`).

## Cautions

- Load **one** schedule line per night into the operational DB — parallel
  lines for the same window double-book the spacecraft.
- Regenerate shortly before execution with a fresh TLE (edit `tle_vzlu` in
  `sched_first.py`); `--eclipse-margin` absorbs small drift only.
- `Schedule.expo` stores the slice-coverage quantum from the time-sliced
  solver (may be up to one slice longer than the true exposure); the true
  per-exposure duration lives on `_chunk_duration` (in-memory only, used by
  `verify_schedule.py` before saving).
- The verification gate (`verify_schedule.py`) deliberately shares no code
  with the visibility pipeline; keep it that way.
- `Schedule`'s DB column is still literally named `time` (`db_column`);
  the Python attribute is `line`. Always filter/query via `.line`, not
  `.time` -- the two are a historical split only, not independent.
