# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.12.1] - 2026-04-10

### Changed
- README.md now defaults to Chinese; English moved to README_en.md
- Updated tool count from 30 to 33 in both READMEs

### Fixed
- `get_longest_trip_on_single_charge`: rewritten with 4-layer CTE and 5-minute gap rule to correctly identify continuous driving chains (previously summed all drives between charges, producing inflated results like 654km over 15 days)
- `get_driver_profile`: fixed milestone thresholds 16,000/30,000 → 160,000/300,000 km to match rank system and Chinese labels
- `generate_monthly_driving_report`: changed aggregation queries from `_query()[0]` to `_query_one()` for efficiency; removed redundant `target_month` double-parsing
- Moved `import random` to top-level imports
- Updated module docstring with 3 new tools

### Added
- New distance milestones at 50,000 km and 100,000 km in `get_driver_profile`
- `get_longest_trip_on_single_charge` now returns `drive_count` and `duration` fields

## [0.11.9] - 2026-04-10

### Fixed
- `check_daily_quest`: use range-based energy calculation

## [0.11.0] - 2026-04-09

### Added
- `get_driver_profile` — driver gamification (rank, milestones, Easter eggs)
- `check_daily_quest` — daily driving quest system
- `get_longest_trip_on_single_charge` — record distance on single charge
- `_parse_date()` helper for timezone-aware date parsing
- `tesla_drives` and `tesla_trips_by_category`: added `start_date`/`end_date` params
- VERSION env var, MCP_DEBUG mode, structured logging
- Input validation for days, month, date format parameters
- Startup fail-fast: connection pool initialized at boot

## [0.7.0] - 2026-04-08

### Changed
- **Performance**: connection pooling (psycopg2 ThreadedConnectionPool, min=2, max=8)
- **Performance**: merged `tesla_status` queries 5→1, `tesla_live` queries 4→1 (LATERAL JOIN)
- **Performance**: replaced correlated subquery address matching with LATERAL + BETWEEN
- **Performance**: registered global Decimal→float adapter
- **Performance**: `_query_one` uses fetchone() instead of fetchall()[0]
- **Performance**: parameterized all f-string CAR_ID/KWH_PER_KM (30+ sites)
- Added TTL cache for car info / software version
- Simplified geofence lookups (Haversine → BETWEEN + Euclidean)
- Raised default query limits (drives/charging 50→500, etc.)
- Added truncation warnings when results hit LIMIT cap
- `tesla_charging_by_location`: added `days` parameter for date filtering
- Connection pool: TCP keepalives, atexit cleanup, null-safety fixes

## [0.1.0] - 2026-03-23

### Added
- Initial release (fork of loddev/mcp-teslamate-fleet)
- 29 tools across TeslaMate + Fleet API
- Configurable battery capacity, electricity rate, gas price via env vars

[0.12.1]: https://github.com/6547709/teslamate-mcp/compare/v0.12.0...v0.12.1
[0.11.9]: https://github.com/6547709/teslamate-mcp/compare/v0.11.0...v0.11.9
[0.11.0]: https://github.com/6547709/teslamate-mcp/compare/v0.7.0...v0.11.0
[0.7.0]: https://github.com/6547709/teslamate-mcp/compare/v0.1.0...v0.7.0
[0.1.0]: https://github.com/lodordev/mcp-teslamate-fleet/releases/tag/v0.1.0
