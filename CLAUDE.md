# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

A single-file **FastMCP** server (`tesla.py`, ~5475 lines) that exposes **38 read-only analytics tools** over a TeslaMate PostgreSQL database. There is no Tesla Owner API token — every tool reads from the local TeslaMate schema (drives, charging_processes, cars, geofences, addresses, positions, etc.). Multi-car is supported via `car_id`; v1.2.x adds optional AMAP (高德) geocoding and QWeather (和风天气) enrichment, both of which silently no-op when keys are unset.

Default transport is **stdio**; set `MCP_TRANSPORT=streamable-http` for the Docker / HTTP deployment on port 8080.

## Build & run

```bash
# Editable install (hatchling backend, requires Python ≥3.10)
cd teslamate-mcp
pip install -e .

# Run locally (stdio, used for desktop MCP clients)
python tesla.py

# Run as HTTP server (Docker / NAS)
MCP_TRANSPORT=streamable-http HTTP_PORT=8080 python tesla.py

# Docker
docker build -t teslamate-mcp:dev .
docker run --rm -p 8080:8080 \
  -e TESLAMATE_DB_HOST=... -e TESLAMATE_DB_PASS=... \
  -e MCP_TRANSPORT=streamable-http \
  teslamate-mcp:dev
```

The Dockerfile builds with `ARG VERSION=dev` and exposes `VERSION` to the app — the runtime picks the version via `_detect_version()` (env `VERSION` → `__version__` constant → `git describe`).

## Tests

```bash
cd teslamate-mcp
python test_all.py    # exit 0 = pass, exit 1 = failures
```

`test_all.py` runs **without a real PostgreSQL** — it monkeypatches `tesla._query` and `tesla._query_one` with SQL-fingerprint-keyed fakes (`_fake_query` / `_fake_query_one` at top of file). Two layers:

- **Layer 1** (`test_unit`, `test_review_fixes`, `test_single_flight`): pure-logic assertions covering the historical bug/perf/issue-fix points (BUG-4, PERF-1/2/4, ISSUE-1..5).
- **Layer 2** (`test_tools`): asyncio-smoke every `@mcp.tool()` registered on the `mcp` object and assert it returns a `str` without raising.

Env defaults are forced before `import tesla` so module-level config picks them up (`TESLAMATE_DB_HOST=localhost`, `USE_METRIC_UNITS=true`, `TIMEZONE=Asia/Shanghai`). To add a regression, append to the appropriate section rather than spinning up a real DB.

## Architecture (big picture)

The whole server is one file. Mental model when navigating it:

1. **Module init (L1–~L440)** — version detection, env-var config, multi-car `_CAR_PARAMS` table, DB pool (`_pool`) lazy init, `mcp = FastMCP(...)` registration, Decimal→float psycopg2 adapter.
2. **Helpers** (sections marked `# -- ... ---`):
   - `# -- Timezone helpers` — `_parse_date` (parse YYYY-MM-DD in USER_TZ then convert to UTC for half-open interval queries), `_format_dt`, `_validate_days`.
   - `# -- DB helper` — `_init_pool`, `_get_conn`, `_put_conn`, `_query`, `_query_one`. The threaded pool is created once at startup (`if __name__ == "__main__": _init_pool()`) and shared.
   - `# -- Simple TTL cache` — `_cached_query_one` / `_cached_query` for rarely-changing rows (car info, geofences). Capped at `TESLA_CACHE_MAX_ENTRIES` (default 500); LRU-ish prune in `_prune_cache`.
   - `# -- Persistent geocode cache` — disk-backed JSON at `~/.cache/teslamate-mcp/geocode.json`, bounded by `TESLA_GEOCODE_CACHE_MAX`.
   - `# -- AMAP geocoding` — `_amap_geocode`, `gcj02_to_wgs84` (GCJ-02→WGS-84 because TeslaMate stores raw GPS).
   - `# -- QWeather async helpers` — `_qweather_now`, `_qweather_locationid` (GeoAPI), `_qweather_historical`, with per-grid-key single-flight locks in `_qw_locid_flight_lock`.
   - `# -- Result-level cache` — `_cached_result` wraps slow async aggregations (`tesla_savings`, `tesla_monthly_report`, `tesla_efficiency_by_temp`, `tesla_charging_by_location`, `tesla_top_destinations`, `tesla_battery_health`).
3. **Tools** — every exported tool follows the same shape: a thin `@mcp.tool()` async wrapper that handles `car_id`/`days`/`date` plumbing, then delegates to a `_compute` helper that does the SQL + formatting. Example: `tesla_status` → no `_compute`, but `tesla_savings` → `_savings_compute`, `tesla_trip_cost` → ~inline. Look for the `_compute` function when you need to change SQL; look at the wrapper when you need to change params/return contract.
4. **Entry point (L5446)** — picks `mcp.run()` vs `mcp.run(transport="streamable-http", ...)` based on `MCP_TRANSPORT`.

### Conventions worth knowing

- **Date handling**: every `start_date` / `end_date` param flows through `_parse_date` → interpreted in `USER_TZ` (env `TIMEZONE`, default `Asia/Shanghai`) → converted to UTC for SQL. Queries use **half-open intervals** (`start_date >= start_utc AND start_date < end_utc`). Don't change this without checking all callers.
- **Look-back caps**: `_validate_days(days, max_days=MAX_LOOKBACK_DAYS)` enforces a positive int ≤ `TESLA_MAX_LOOKBACK_DAYS` (default 3650). Pass `days=None` for "all time".
- **Row limits**: every tool that returns a list reads its cap from a `TESLA_LIMIT_*` env var (e.g. `LIMIT_DRIVES=1000`, `LIMIT_CHARGING=500`). Set to `-1` for unlimited. See `# -- Query limits` section.
- **Multi-car**: `_effective_car_id(car_id)` falls back to global `CAR_ID`. `_get_car_config(car_id)` reads `_CAR_PARAMS` (built from `TESLA_CAR_PARAMS` JSON env), falling back to single-car `TESLA_BATTERY_KWH` / `TESLA_BATTERY_RANGE_KM`.
- **Unit formatting**: never emit km/°C/kWh/¥ directly — use `_format_distance`, `_format_temp`, `_format_efficiency`, `_format_cost`, `_km_to_mi`, `_c_to_f`. They honor `USE_METRIC_UNITS`.
- **Optional integrations**: AMAP and QWeather are guarded by `AMAP_GEOCODE_ENABLED` / `QWEATHER_ENABLED` flags computed at import time. Missing key = the path is **skipped**, not an error — preserve this when touching the code.
- **Caching discipline**: read-only tools should use `_cached_query_one` for slow-changing master data (car/sw version) and `_cached_result` for expensive aggregations. Be careful to keep cache keys stable across versions; bumping TTLs is fine, renaming keys silently invalidates deployments.
- **Decimal handling**: `psycopg2.extensions.new_type` is registered globally so `DECIMAL` columns come back as `float` — keep that registration or fix every aggregate that does arithmetic.

### Where to look for what

| If you want to change… | Look at… |
|---|---|
| A new env var / config knob | `# -- Configuration` near top, then `os.environ.get(...)` usage |
| DB schema for a metric | grep for the table name (`drives`, `charging_processes`, `positions`, `addresses`, `geofences`, `states`, `charges`) — every tool's `_compute` inlines SQL |
| Tool signature / parameter validation | the `@mcp.tool()` wrapper, not the `_compute` helper |
| Cache TTL or eviction | `_prune_cache`, `_cached_query*`, `_cached_result` |
| AMAP coordinate math | `_amap_geocode`, `gcj02_to_wgs84` |
| QWeather flow | `_qweather_now`, `_qweather_locationid`, `_qweather_historical`, `_qw_locid_flight_lock` |
| Unit output | `_format_*` helpers and `USE_METRIC_UNITS` |

## Versioning

`__version__` at the top of `tesla.py` is the source of truth; bump it when tagging. `_detect_version()` prefers `VERSION` env (set by Docker `--build-arg VERSION=...`), then the constant, then `git describe`. CHANGELOG.md tracks release notes by version.

## Reference docs in this repo

- `README.md` (中文) / `README_en.md` — full user-facing docs, all env vars, tool catalog, docker-compose template
- `CHANGELOG.md` — per-version notes (v1.2.x is current)
- `PERFORMANCE_IMPLEMENTATION.md`, `PERFORMANCE_REVIEW.md` — rationale for the caching layer
- `STATS_LOGIC_REVIEW.md` — math behind efficiency/savings/eco tools
- `TEST_REPORT.md` — coverage history
- `docs/deployment/`, `docs/superpowers/` — deployment recipes and AI-process notes