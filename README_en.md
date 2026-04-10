# TeslaMate MCP Server

[English](README_en.md) | [中文](README.md)

A Model Context Protocol (MCP) server providing Tesla vehicle analytics through **TeslaMate** PostgreSQL database. Read-only — no vehicle commands. Works with [Claude Code](https://claude.ai/code), [OpenClaw](https://openclaw.dev), and any MCP-compatible client.

**Upstream:** This project is a fork of [loddev/mcp-teslamate-fleet](https://github.com/lodordev/mcp-teslamate-fleet), heavily customized for this deployment.

---

## Features

**33 tools** across seven categories — all read-only from TeslaMate PostgreSQL:

### 🚗 Vehicle Status

| Tool | Description |
|------|-------------|
| `tesla_status` | Current state — battery, range, location, climate, odometer |
| `tesla_live` | Latest polled state (GPS, battery, climate, TPMS, charging) |
| `tesla_tpms_status` | Current tyre pressures with anomaly warnings |
| `tesla_tpms_history` | Recent TPMS pressure history |

### 📊 Trips & Driving

| Tool | Description |
|------|-------------|
| `tesla_drives` | Recent drives with distance, duration, efficiency |
| `tesla_driving_score` | Driving score (acceleration, braking, speed habits) |
| `tesla_trips_by_category` | Filter trips by category (commute / shopping / leisure / long_trip / other) |
| `tesla_trip_categories` | Trip count breakdown by category |
| `tesla_longest_trips` | Top drives ranked by distance |
| `tesla_top_destinations` | Most visited locations |
| `tesla_location_history` | Where the car has been — time at each location |

### 🔋 Battery & Charging

| Tool | Description |
|------|-------------|
| `tesla_charging_history` | Charging sessions over N days |
| `tesla_charging_by_location` | Charging patterns by location (supports date filter) |
| `tesla_battery_health` | Battery degradation trend (range at 100% over time) |
| `tesla_vampire_drain` | Battery loss while parked (overnight drain analysis) |

### ⚡ Energy & Efficiency

| Tool | Description |
|------|-------------|
| `tesla_efficiency` | Energy consumption trends (Wh/km weekly averages) |
| `tesla_efficiency_by_temp` | Efficiency curve by outside temperature |
| `tesla_monthly_report` | Monthly driving report with comparison to previous month |
| `tesla_monthly_summary` | Monthly summary table (distance / kWh / cost / efficiency) |

### 💰 Savings & Eco

| Tool | Description |
|------|-------------|
| `tesla_savings` | Gas savings scorecard — how much you've saved vs a gas car |
| `tesla_trip_cost` | Estimate trip cost to a destination (kWh, cost, range check) |
| `calculate_eco_savings_vs_icev` | EV vs ICEV cost/CO₂ comparison with tree equivalents |

### 🏆 Achievements & Fun

| Tool | Description |
|------|-------------|
| `check_driving_achievements` | Detect achievements (极限续航幸存者 / 午夜幽灵 / 冰雪勇士) |
| `generate_travel_narrative_context` | Travel timeline for LLM-powered blogging / Vlog scripts |
| `generate_weekend_blindbox` | Weekend "memory blindbox" — rare one-time destination recommendation |
| `generate_monthly_driving_report` | Polished Markdown monthly report with Emoji |
| `get_vehicle_persona_status` | Vehicle persona metrics (activity / fatigue / extremes / health) |
| `get_charging_vintage_data` | Single charge session detailed parameters |
| `get_driver_profile` | Driver rank, milestones, Easter eggs |
| `check_daily_quest` | Today's random driving challenge |
| `get_longest_trip_on_single_charge` | Longest distance between two charges |

### 🔧 System & History

| Tool | Description |
|------|-------------|
| `tesla_state_history` | Vehicle state transitions (online / asleep / offline) |
| `tesla_software_updates` | Firmware version history |

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

### Timezone & Display

| Variable | Default | Description |
|----------|---------|-------------|
| `TIMEZONE` | `Asia/Shanghai` | Timezone for all output dates (IANA timezone name, e.g. `Asia/Shanghai`, `America/Los_Angeles`) |

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

**Battery capacity reference (China):**

| Year | Model | Version | Battery (kWh) | Range (km) | Note |
|------|-------|---------|--------------|------------|------|
| 2014-2016 | Model S | Early imported (60/75/85/90) | 60-90 | 280-440 | Early 18650 NCM |
| 2016-2018 | Model S/X | 100D series (imported) | 100.0 | 450-510 | Panasonic 18650 NCM |
| 2019.02 | Model 3 | Imported Performance / Long Range RWD | 75.0 | ~490 | Panasonic 2170 NCM |
| 2019.05 | Model 3 | Imported Standard Range+ | 52.0 | ~380 | Panasonic 2170 NCM |
| 2019.12 | Model 3 | China SR (first batch) | 52.5 | ~380 | CATL LFP / NCM |
| 2020.04 | Model 3 | China Long Range RWD | 75.0 | ~490 | LG NCM |
| 2021.01 | Model Y | China Long Range / Performance | 76.8/78.4 | 480-505 | LG NCM |
| 2021.07 | Model Y | China RWD (SR) | 60.0 | ~435 | CATL LFP |
| 2021.11 | Model 3 | China RWD (60 kWh) | 60.0 | ~439 | CATL LFP |
| 2022.03 | Model 3 | 2022 Performance (P) | 78.4 | ~507 | LG NCM |
| 2023.01 | Model S/X | New generation (Plaid/dual motor) | 100.0 | 520-620 | NCM (18650 improved) |
| 2023.09 | Model 3 | Refresh RWD / Long Range | 60/78.4 | 438-550 | LFP / NCM |
| 2024.04 | Model 3 | Refresh Performance (P) | 78.4 | ~480 | LG NCM |
| 2025.01 | Model 3+ | Refresh Long Range RWD | 78.4 | ~620 | NCM (new) |
| 2025.03 | Model Y L | Long Range 6-seater | 82.0 | ~580 | NCM |

### TPMS Thresholds (Optional)

| Variable | Default | Description |
|----------|---------|-------------|
| `TESLA_TPMS_MIN_THRESHOLD` | `2.0` | Low pressure warning (bar) |
| `TESLA_TPMS_MAX_THRESHOLD` | `2.5` | High pressure warning (bar) |

### Query Limits

Set to `-1` for unlimited results.

| Variable | Default | Description |
|----------|---------|-------------|
| `TESLA_LIMIT_DRIVES` | `500` | Max drives returned by `tesla_drives` |
| `TESLA_LIMIT_CHARGING` | `500` | Max charging sessions by `tesla_charging_history` |
| `TESLA_LIMIT_TRIP_CATEGORIES` | `500` | Drives analyzed by `tesla_trip_categories` |
| `TESLA_LIMIT_BATTERY_HEALTH` | `60` | Monthly snapshots in `tesla_battery_health` |
| `TESLA_LIMIT_BATTERY_SAMPLES` | `20` | Fallback sample limit for `tesla_battery_health` |
| `TESLA_LIMIT_LOCATION_HISTORY` | `50` | Location clusters in `tesla_location_history` |
| `TESLA_LIMIT_STATE_HISTORY` | `500` | State transitions in `tesla_state_history` |
| `TESLA_LIMIT_SOFTWARE_UPDATES` | `20` | Software updates returned by `tesla_software_updates` |
| `TESLA_LIMIT_CHARGING_BY_LOCATION` | `50` | Locations in `tesla_charging_by_location` |
| `TESLA_LIMIT_TPMS_HISTORY` | `30` | TPMS records in `tesla_tpms_history` |
| `TESLA_LIMIT_VAMPIRE_DRAIN` | `50` | Drain events in `tesla_vampire_drain` |

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
