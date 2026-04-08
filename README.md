# TeslaMate MCP Server

[English](README.md) | [中文](README_zh.md)

A Model Context Protocol (MCP) server providing Tesla vehicle analytics through **TeslaMate** PostgreSQL database. Read-only — no vehicle commands. Works with [Claude Code](https://claude.ai/code), [OpenClaw](https://openclaw.dev), and any MCP-compatible client.

**Upstream:** This project is a fork of [loddev/mcp-teslamate-fleet](https://github.com/lodordev/mcp-teslamate-fleet), heavily customized for this deployment.

---

## Features

**23+ tools** across four categories:

| Category | Tools | Data Source |
|----------|-------|-------------|
| **Status** | `tesla_status`, `tesla_drives`, `tesla_charging_history`, `tesla_battery_health`, `tesla_efficiency`, `tesla_location_history`, `tesla_state_history`, `tesla_software_updates` | TeslaMate DB |
| **Analytics** | `tesla_savings`, `tesla_trip_cost`, `tesla_efficiency_by_temp`, `tesla_charging_by_location`, `tesla_top_destinations`, `tesla_longest_trips`, `tesla_monthly_summary`, `tesla_vampire_drain`, `calculate_eco_savings_vs_ice` | TeslaMate DB |
| **Enhanced** | `tesla_driving_score`, `tesla_trips_by_category`, `tesla_trip_categories`, `tesla_monthly_report`, `tesla_tpms_status`, `tesla_tpms_history`, `generate_travel_narrative_context`, `get_vehicle_persona_status` | TeslaMate DB |
| **Live** | `tesla_live` (GPS, battery, climate, charging) | TeslaMate DB |

### New Tools

#### `calculate_eco_savings_vs_ice` — Eco Savings Calculator
Compare Tesla's electricity costs vs a hypothetical ICE vehicle over the same distance.

| Param | Default | Description |
|-------|---------|-------------|
| `days` | `30` | Lookback days |
| `ice_mpg` | `8.0` | ICE vehicle fuel consumption (L/100km) |
| `gas_price` | `8.0` | Gas price per litre (RMB) |
| `electricity_price` | `0.5` | Electricity price per kWh (RMB) |

Returns JSON: ICE baseline (fuel/cost/CO2), EV actual CO2, money saved, CO2 reduced, tree equivalents.

#### `generate_travel_narrative_context` — Travel Narrative Timeline Generator
Extracts structured drive and stop data for LLM-powered travel blogging or Vlog scripting.

| Param | Description |
|-------|-------------|
| `start_time` | ISO8601 start time |
| `end_time` | ISO8601 end time |

Returns a timeline JSON array with from/to names, distance, duration, temperature, stay duration after arrival, and stay type (important_stop / short_stop / none).

#### `get_vehicle_persona_status` — Vehicle Persona Status Panel
Provides activity, fatigue, extreme behaviour, and health metrics for an LLM to roleplay a "vehicle with personality".

| Param | Default | Description |
|-------|---------|-------------|
| `days_lookback` | `7` | Lookback days |

Returns JSON: activity (total km, idle %), fatigue (longest continuous drive), extremes (max speed), health (vampire drain estimate), and Chinese persona label (元气满满 / 疲惫不堪 / 闲得发慌 / 悠闲自得).

---

## Quick Start

### Deploy on Synology NAS (Docker)

This service is designed to run alongside your existing TeslaMate installation.

**1. Add to your TeslaMate `docker-compose.yml`:**

```yaml
services:
  teslamate-mcp:
    image: ghcr.io/<YOUR-GITHUB-USERNAME>/teslamate-mcp:latest
    container_name: teslamate-mcp
    restart: always
    ports:
      - "30002:8080"
    environment:
      # TeslaMate database (same values as your teslamate service)
      - TESLAMATE_DB_HOST=database
      - TESLAMATE_DB_PORT=5432
      - TESLAMATE_DB_USER=teslamate
      - TESLAMATE_DB_PASS=secret
      - TESLAMATE_DB_NAME=teslamate
      # HTTP server mode
      - MCP_TRANSPORT=streamable-http
      - HTTP_HOST=0.0.0.0
      - HTTP_PORT=8080
      # Units and currency
      - USE_METRIC_UNITS=true      # true = km/°C/¥, false = mi/°F/$
      - TESLA_ELECTRICITY_RATE_RMB=0.6  # RMB per kWh (your electricity rate)
      # Vehicle
      - TESLA_CAR_ID=1
      - TESLA_BATTERY_KWH=75        # Your battery capacity in kWh
      - TESLA_BATTERY_RANGE_KM=525  # EPA range at 100% in km
    depends_on:
      - database
```


**2. Start the container:**

```bash
docker-compose up -d teslamate-mcp
```

**3. Verify it's running:**

```bash
docker logs teslamate-mcp
```

You should see:
```
Uvicorn running on http://0.0.0.0:8080 (Press CTRL+C to quit)
```

---

### Configure MCP Client

#### OpenClaw

In your OpenClaw settings, add a new MCP server:

```json
{
  "mcpServers": {
    "teslamate": {
      "url": "http://192.168.10.200:30002/mcp"
    }
  }
}
```

#### Claude Code (`~/.claude/settings.json` or project `.mcp.json`)

```json
{
  "mcpServers": {
    "tesla": {
      "url": "http://192.168.10.200:30002/mcp"
    }
  }
}
```

> **Note:** If Claude Code is running on a different machine than your NAS, ensure port 30002 is accessible through your network.

---

## Environment Variables

All configuration is via environment variables.

### TeslaMate Database (Required)

| Variable | Default | Description |
|----------|---------|-------------|
| `TESLAMATE_DB_HOST` | *(required)* | PostgreSQL host — use `database` if on same docker network |
| `TESLAMATE_DB_PORT` | `5432` | PostgreSQL port |
| `TESLAMATE_DB_USER` | `teslamate` | PostgreSQL user |
| `TESLAMATE_DB_PASS` | *(required)* | PostgreSQL password |
| `TESLAMATE_DB_NAME` | `teslamate` | Database name |

### Server Mode

| Variable | Default | Description |
|----------|---------|-------------|
| `MCP_TRANSPORT` | `stdio` | `stdio` for CLI, `streamable-http` for container |
| `HTTP_HOST` | `0.0.0.0` | Bind address |
| `HTTP_PORT` | `8080` | HTTP port inside container |

### Units & Currency

| Variable | Default | Description |
|----------|---------|-------------|
| `USE_METRIC_UNITS` | `false` | `true` = km/°C/¥/Wh/km, `false` = mi/°F/$/Wh/mi |
| `TESLA_ELECTRICITY_RATE_RMB` | `0.6` | Electricity cost in RMB per kWh |
| `TESLA_ELECTRICITY_RATE_USD` | `0.12` | Electricity cost in USD per kWh (fallback) |

### Vehicle

| Variable | Default | Description |
|----------|---------|-------------|
| `TESLA_CAR_ID` | `1` | TeslaMate car ID (check TeslaMate dashboard) |
| `TESLA_BATTERY_KWH` | `75` | Usable battery capacity in kWh |
| `TESLA_BATTERY_RANGE_KM` | `525` | EPA range at 100% in km |

**Battery capacity reference:**

| Vehicle | Battery (kWh) | Range (km) |
|---------|--------------|------------|
| Model 3 Standard Range | 54 | 350 |
| Model 3 Long Range | 75 | 500 |
| Model Y Long Range | 75 | 525 |
| Model S Long Range | 100 | 650 |
| Model X Long Range | 100 | 560 |

### TPMS Thresholds (Optional)

| Variable | Default | Description |
|----------|---------|-------------|
| `TESLA_TPMS_MIN_THRESHOLD` | `2.0` | Low pressure warning (bar) |
| `TESLA_TPMS_MAX_THRESHOLD` | `2.5` | High pressure warning (bar) |

### Query Limits

Set to `-1` for unlimited results.

| Variable | Default | Description |
|----------|---------|-------------|
| `TESLA_LIMIT_DRIVES` | `50` | Max drives returned by `tesla_drives` |
| `TESLA_LIMIT_CHARGING` | `50` | Max charging sessions by `tesla_charging_history` |
| `TESLA_LIMIT_TRIP_CATEGORIES` | `100` | Drives analyzed by `tesla_trip_categories` |
| `TESLA_LIMIT_BATTERY_HEALTH` | `24` | Monthly snapshots in `tesla_battery_health` |
| `TESLA_LIMIT_BATTERY_SAMPLES` | `20` | Fallback sample limit for `tesla_battery_health` |
| `TESLA_LIMIT_LOCATION_HISTORY` | `20` | Location clusters in `tesla_location_history` |
| `TESLA_LIMIT_STATE_HISTORY` | `100` | State transitions in `tesla_state_history` |
| `TESLA_LIMIT_SOFTWARE_UPDATES` | `20` | Software updates returned by `tesla_software_updates` |
| `TESLA_LIMIT_CHARGING_BY_LOCATION` | `15` | Locations in `tesla_charging_by_location` |
| `TESLA_LIMIT_TPMS_HISTORY` | `20` | TPMS records in `tesla_tpms_history` |
| `TESLA_LIMIT_VAMPIRE_DRAIN` | `20` | Drain events in `tesla_vampire_drain` |

---

## Architecture

Single-file Python server (~2700 lines) using **FastMCP**. All data comes directly from TeslaMate PostgreSQL:

```
┌─────────────┐     ┌──────────────┐     ┌───────────┐     ┌────────────┐
│  TeslaMate   │────▶│   Postgres   │────▶│ tesla.py  │────▶│ MCP Client │
│  (logger)    │     │  (TeslaMate) │     │(HTTP/:8080)│     │(OpenClaw,   │
└─────────────┘     └──────────────┘     └───────────┘     │ Claude Code)│
                                                            └────────────┘
```

**How it works:**
- All data is read directly from TeslaMate's PostgreSQL database
- No Tesla Owner API, no separate Tesla Developer account, no API tokens required

---

## GitHub Actions

Docker images are built and pushed to GitHub Container Registry on each version tag:

```bash
# Tag a release
git tag v0.1.0
git push origin v0.1.0
```

The image will be available at `ghcr.io/<your-username>/teslamate-mcp:<tag>`.

---

## Limitations

- **Single vehicle** — queries use a configurable `car_id`
- **Imperial units by default** — set `USE_METRIC_UNITS=true` for metric
- **Estimated energy** — kWh is estimated from ideal range deltas (~90-95% accuracy)

---

## Acknowledgments

This project is a fork of [loddev/mcp-teslamate-fleet](https://github.com/lodordev/mcp-teslamate-fleet) by [@lodordev](https://github.com/lodordev). The original project provided the foundation for Tesla MCP integration. This fork removes command functionality for security, uses TeslaMate database as the sole data source, and adds enhanced analytics features.

Built with [FastMCP](https://github.com/jlowin/fastmcp) and [TeslaMate](https://github.com/teslamate-org/teslamate).

---

## License

MIT
