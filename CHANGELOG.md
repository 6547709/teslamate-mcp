# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.1] - 2026-06-26

Application-layer hardening & performance release — **0 database changes**. Fixes one cross-tool inconsistency bug, adds input validation, bounded caches, and pushes trip classification into SQL. All 36 tools validated by a new no-database test harness (57/57 assertions passed).

### Fixed
- **Vampire-drain threshold inconsistency (BUG-4)** — the standalone `tesla_vampire_drain` tool used an 8-hour parked threshold while `generate_monthly_driving_report` and `get_vehicle_persona_status` used 3 hours, producing contradictory results across tools. Unified all three behind shared constants `VAMPIRE_MIN_HOURS` (8) / `VAMPIRE_MAX_HOURS` (168), overridable via `TESLA_VAMPIRE_MIN_HOURS` / `TESLA_VAMPIRE_MAX_HOURS`.

### Added
- **`_validate_days()` helper** — centralized look-back validation (rejects negative / zero / oversized `days`; cap `TESLA_MAX_LOOKBACK_DAYS`, default 3650). Wired into 10 date-range tools plus `n` / `month` / `start_month` / `end_month` checks in `tesla_driving_score`.
- **`test_all.py`** — full functional test harness that runs with **no live database** (monkeypatches `_query` / `_query_one` with a fake-DB layer). Three layers: fix-point unit tests, smoke-call of every `@mcp.tool()`, and error-path validation. 57/57 passed.

### Changed
- **`tesla_trips_by_category` (PERF-4)** — `shopping` / `leisure` classification now pre-filters address names in SQL via `ILIKE ANY(ARRAY[...])`, shrinking the candidate set from a potential full-table scan to keyword-matching rows only (Python still re-checks precedence). Read-only; no schema change.
- **`_classify_trip` (PERF-1)** — shopping / leisure keyword lists hoisted to module-level pre-lowercased tuples instead of being rebuilt and re-lowercased on every call (invoked thousands of times inside `tesla_trip_categories`).
- **In-memory caches (PERF-2)** — `_cache` / `_result_cache` now carry a per-entry TTL and run lazy garbage-collection via `_prune_cache()`, capped at `TESLA_CACHE_MAX_ENTRIES` (default 500), preventing unbounded growth in long-running HTTP-mode servers.
- **`tesla_trip_cost` (ISSUE-3)** — rejects too-short/ambiguous queries (`< 2` chars) with a clear message, and ranks local-address candidates by **actual visit frequency** (from `drives.end_address_id`) so the most-relevant place wins instead of arbitrary `id DESC`.
- **`_find_nearby_geofence` (ISSUE-2)** — planar geofence distance now multiplies the longitude delta by `cos(latitude)`, removing the ~18% longitude-axis looseness at mid/high latitudes.
- **Persistent geocode cache (ISSUE-4)** — `~/.cache/teslamate-mcp/geocode.json` is now bounded at `TESLA_GEOCODE_CACHE_MAX` entries (default 1000) with FIFO/LRU eviction, so repeated misses can no longer grow the file without bound.
- **`tesla_status` charging detection (ISSUE-5)** — open-session window widened 24h → 48h and now also honours live vehicle `state = 'charging'`, so very long destination AC charges are no longer misreported as "not charging".

### Performance
- `_classify_trip` hot loop: ~30–40% less string work per call (no per-call list build / `.lower()`).
- `tesla_trips_by_category(shopping|leisure)`: candidate rows scanned cut from up to 2000 (multi-batch) to keyword-matched rows in a single query.
- Memory: in-process caches now bounded; no steady-state growth under sustained HTTP traffic.

### Breaking Changes
- None. All tool signatures and return formats remain backwards-compatible with v1.1.0.

[1.1.1]: https://github.com/6547709/teslamate-mcp/releases/tag/v1.1.1

## [1.1.0] - 2026-04-22

Performance & observability release — **0 database changes**, pure in-app optimizations. Cold-cache workload reduced by 28%, warm-cache by 69%. New diagnostic tool. 36/36 tools validated.

### Added
- **`tesla_version()` tool** — first tool in the catalog, returns server version, tool count, Python / fastmcp / psycopg2-binary versions, timezone, units, and live TeslaMate DB health check. Use this to confirm deployment identity and connectivity.
- **FastMCP metadata** — server now advertises `name=teslamate-mcp`, `version`, `instructions`, and `website_url` during MCP handshake (visible to any compliant client without a tool call).
- **`__version__` constant** with multi-level resolution: `VERSION` env var (Docker build-arg) → hardcoded `__version__` → `git describe` → `"dev"`.
- **Persistent Nominatim geocode cache** — `~/.cache/teslamate-mcp/geocode.json`, cross-process and thread-safe.
- **Result-level cache framework** (`_cached_result`) — wraps entire tool output with per-key TTL.
- **`PERFORMANCE_REVIEW.md`**, **`PERFORMANCE_IMPLEMENTATION.md`**, **`TEST_REPORT.md`** committed to repo for transparency.

### Changed
- **`tesla_savings`**: 4 independent queries → **2 queries** via `FILTER (WHERE ...)` aggregate condition. Cold 200ms → 8ms (27×).
- **`tesla_monthly_report`**: 4 queries → **2 queries** via `FILTER`. Cold 300ms → 5ms (60×). Historical months cached 1 day; current month always live.
- **`tesla_trip_cost`**: 3-stage fallback — first search local TeslaMate `addresses` table (1,700+ visited places), then persistent file cache, finally Nominatim. Local hits drop cold latency from 1296ms to ~15ms (86×).
- **`tesla_battery_health`** / **`tesla_efficiency_by_temp`** / **`tesla_charging_by_location`** / **`tesla_top_destinations`**: added result-level caching (1h / 30min / 30min / 30min). Warm hits drop to microseconds.
- **`LIMIT_DRIVES`** default **500 → 1000**; **`LIMIT_TRIP_CATEGORIES`** default **500 → 1000**. `tesla_drives(365+)` now covers 247 days of history instead of 131 (+88%). Override via `TESLA_LIMIT_DRIVES` / `TESLA_LIMIT_TRIP_CATEGORIES` envs.
- **`tesla_drives` header** now displays the actual data window when the requested `days` exceeds available data (e.g. `days=10000` shows `2025-08-17 → 2026-04-20, 247 days of data, 1000 trips` instead of a misleading "last 10000 days").

### Fixed
- **Bug: `tesla_trip_cost("")` false match** — empty/whitespace destination no longer matches arbitrary addresses via `ILIKE '%%'`. Input is now validated with a clear error message.

### Performance
- Full suite benchmark (36 tools, live database):
  - v1.0.0: 4400 ms · avg 126 ms/call
  - v1.1.0 cold cache: **3168 ms** · avg 90 ms/call (↓ 28%)
  - v1.1.0 warm cache: **1369 ms** · avg 39 ms/call (↓ 69%)
- Cache hit speed-ups: `tesla_battery_health` 8827× · `tesla_top_destinations` 1612× · `tesla_charging_by_location` 125× · `tesla_savings` 99× · `tesla_efficiency_by_temp` 69× · `tesla_monthly_report` 31×
- **6/6** cached tools verified deterministic (hash cold == warm == 3rd call).
- **15/15** edge-case inputs handled gracefully (zero crashes).

### Breaking Changes
- None. All tool signatures and return formats are backwards-compatible with v1.0.0.

[1.1.0]: https://github.com/6547709/teslamate-mcp/releases/tag/v1.1.0

## [1.0.0] - 2026-04-21

Major stability & accuracy overhaul. 35 tools, 30+ bugs fixed, 9 statistics tools rewritten for real-world correctness, all validated against a live TeslaMate database (35/35 passed).

### Fixed — P0 (Critical)
- **Midnight ghost**: `tesla_status` no longer returns stale data during 00:00–05:00 when TeslaMate is idle; now falls back to last known position + explicit freshness marker.
- **LATERAL ordering**: Multi-row LATERAL joins now sort by `start_date` explicitly, fixing random row selection on PG 14+.
- **Cache lock**: Added thread-safe locks around `_cache` and `ROUTINE_CACHE` to eliminate race conditions under concurrent MCP calls.
- **Timezone drift**: `generate_travel_narrative_context` now uses `USER_TZ` consistently instead of naive UTC timestamps.
- **Redundant query removal** in `tesla_status` — single-query fast path cut latency by ~40%.
- **Energy source correction**: Efficiency and cost calculations now use `charging_processes.charge_energy_added` (real grid intake) instead of battery-delta estimates.

### Fixed — P1 (High)
- **Nominatim compliance**: Added `User-Agent`, rate-limiting and `try/except` around all reverse-geocoding calls per OSM policy.
- **NULL guards**: Added `lat/lon` NULL checks in 6 call sites to prevent `TypeError` on cars with positions but no GPS fix.
- **Trip cost formula**: Fixed off-by-one-hundred in percentage math (`.0f%%` → proper decimal handling).
- **Vampire drain rewrite**: Now derives idle windows from the event table (`drive_end` → next `drive`/`charge`) with positions-join for `battery_level`, matching TeslaMate's own UI logic.
- **tesla_charges limit**: Added max `limit=500` cap to prevent OOM on large histories.
- **Connection autocommit**: `_get_conn` now sets `autocommit=True` — no more stuck transactions on read-only queries.
- **Month-boundary math** in `tesla_monthly_summary` uses `USER_TZ`-aware date math.

### Fixed — P2 (Medium)
- **LATERAL → address_id JOIN** (5 sites): replaced expensive LATERAL subqueries with direct `cp.address_id JOIN addresses` — 3-10× faster on hot paths.
- **trips_by_category** rebuilt with a single-query SQL fast path (was 5 sequential queries).
- **longest_trip** now only considers closed drive windows (`end_date IS NOT NULL`), eliminating phantom 72-hour "trips" from orphaned rows.
- **ROUTINE_CACHE_TTL** raised to 1h for car_params / geofences.
- Log format now includes `%z` for timezone-aware timestamps.
- `TESLA_CAR_PARAMS` validation reports per-field errors instead of a single generic message.
- Modern type annotations (`int | None = None`).

### Fixed — P3 (Low)
- Defensive `/(num_drives or 1)` in 5 aggregation paths.
- `defaultdict` import hoisted to module scope.
- Docstrings reorganized into 7 categories across all 35 tools for better MCP discovery.
- `git rm --cached` on 3 stray `.DS_Store` files.

### Changed — Statistics Logic Rewrites (9 tools)
- **`tesla_status` / `tesla_live_data`**: Range now prefers `positions.ideal_battery_range_km` (reflects real battery degradation: 362.2 → 328.7 km observed). Added 24h window for `is_charging` detection.
- **`tesla_tpms_history`**: 4-hour bucket aggregation (default limit 180); only attaches MIN/MAX when intra-bucket delta > 0.2 bar. SQL uses `%%` for modulo escaping in psycopg2.
- **`tesla_drives`**: Allows negative energy values to correctly mark regenerative (↻) recovery trips.
- **`tesla_driving_score`**: New thresholds — harsh accel 100 kW / harsh brake -50 kW / speed limit 135 km/h. Score multiplier ×10 → ×5 (avoids 54pt baseline → realistic 93.5).
- **`tesla_trips_by_category`**: Chinese keyword dictionary (万达/银泰/火锅/超市 etc.). "Shopping" recognition jumped from 97% "other" to 25% correctly classified.
- **`tesla_top_destinations`**: Coordinate clustering `FLOOR(lat/0.002)*0.002` (~220 m grid) + `MODE() WITHIN GROUP` for representative address. "万达·天樾" merged from 552 → 626 visits.
- **`tesla_location_history`**: `ORDER BY span_hours`, coordinate precision 0.002° (~220 m — user-confirmed granularity for multi-zone residential compounds).
- **`tesla_efficiency`**: LEFT JOIN `charging_processes` by ISO week; output includes "（实际充电 X kWh）" for transparency.

### Added
- `STATS_LOGIC_REVIEW.md` — full audit of all 35 tools' statistical validity, shipped as a Release asset.
- `%z` timezone marker in all log output.
- Per-field validation errors for `TESLA_CAR_PARAMS`.

### Performance
- Full test suite: **35/35 tools passed** in 4.4 s total (avg 126 ms per call) against live database.
- Read-only wrapper intercepts all write attempts — verified.
- Slowest queries: `battery_health` 1588 ms, `trip_cost` 1296 ms (includes Nominatim round-trip).

### Breaking Changes
- None. All fixes are backwards-compatible. Existing MCP clients require no configuration changes.

[1.0.0]: https://github.com/6547709/teslamate-mcp/releases/tag/v1.0.0

## [0.1.0] - 2026-03-23

### Added
- Initial release with 29 tools across TeslaMate + Fleet API
- 8 read tools: status, drives, charging history, battery health, efficiency, location history, state history, software updates
- 8 analytics tools: savings, trip cost, efficiency by temp, charging by location, top destinations, longest trips, monthly summary, vampire drain
- 1 live data tool via Fleet API
- 12 command tools: climate, charging, locks, horn, lights, trunk, sentry mode
- Graceful degradation — works with TeslaMate only, Fleet API only, or both
- Configurable battery capacity, electricity rate, gas price via env vars
- Safety: confirm=True required for unlock/trunk, 40 commands/day rate limit
- Glama inspection support (glama.json)
- CI linting with ruff
- PyPI package (`mcp-teslamate-fleet`) via GitHub Actions trusted publishing

[0.1.0]: https://github.com/lodordev/mcp-teslamate-fleet/releases/tag/v0.1.0
