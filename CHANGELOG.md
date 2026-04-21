# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
