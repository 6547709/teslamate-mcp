# TeslaMate MCP Server

MCP server for **TeslaMate** historical analytics and **Tesla Owner API** real-time data. Read-only — no vehicle commands. Works with Claude Code, Claude Desktop, Cursor, OpenClaw, and any MCP-compatible client.

## Features

**20+ tools** across three categories:

| Category | Tools | Backend |
|----------|-------|---------|
| **History** | `tesla_status`, `tesla_drives`, `tesla_charging_history`, `tesla_battery_health`, `tesla_efficiency`, `tesla_location_history`, `tesla_state_history`, `tesla_software_updates` | TeslaMate |
| **Analytics** | `tesla_savings`, `tesla_trip_cost`, `tesla_efficiency_by_temp`, `tesla_charging_by_location`, `tesla_top_destinations`, `tesla_longest_trips`, `tesla_monthly_summary`, `tesla_vampire_drain` | TeslaMate |
| **Enhanced** | `tesla_driving_score`, `tesla_trips_by_category`, `tesla_trip_categories`, `tesla_monthly_report`, `tesla_tpms_status`, `tesla_tpms_history` | TeslaMate |
| **Live** | `tesla_live` | Tesla Owner API |

## Quick Start

### Docker (Recommended)

Add to your existing TeslaMate `docker-compose.yml`:

```yaml
services:
  teslamate-mcp:
    image: ghcr.io/<your-github-username>/teslamate-mcp:latest
    restart: always
    ports:
      - "30002:8080"
    environment:
      - ENCRYPTION_KEY=<your-teslamate-encryption-key>
      - TESLAMATE_DB_HOST=database
      - TESLAMATE_DB_PORT=5432
      - TESLAMATE_DB_USER=teslamate
      - TESLAMATE_DB_PASS=secret
      - TESLAMATE_DB_NAME=teslamate
      - MCP_TRANSPORT=streamable-http
      - HTTP_HOST=0.0.0.0
      - HTTP_PORT=8080
      - USE_METRIC_UNITS=true
      - TESLA_ELECTRICITY_RATE_RMB=0.6
      - TESLA_CAR_ID=1
      - TESLA_BATTERY_KWH=75
      - TESLA_BATTERY_RANGE_KM=525
    depends_on:
      - database
```

### Claude Code (`~/.claude/mcp.json`)

```json
{
  "mcpServers": {
    "tesla": {
      "command": "docker",
      "args": [
        "run", "--rm", "-i",
        "--env-file", "/path/to/teslamate-mcp.env",
        "ghcr.io/<your-github-username>/teslamate-mcp:latest"
      ]
    }
  }
}
```

### Local Install

```bash
pip install -e .
mcp-teslamate-fleet
```

## Prerequisites

- **TeslaMate** running with PostgreSQL database accessible
- **ENCRYPTION_KEY** from your TeslaMate installation (used to decrypt Owner API tokens stored in TeslaMate's database)

## Configuration

All configuration is via environment variables.

### TeslaMate Database

| Variable | Default | Description |
|----------|---------|-------------|
| `TESLAMATE_DB_HOST` | *(required)* | Postgres host |
| `TESLAMATE_DB_PORT` | `5432` | Postgres port |
| `TESLAMATE_DB_USER` | `teslamate` | Postgres user |
| `TESLAMATE_DB_PASS` | *(required)* | Postgres password |
| `TESLAMATE_DB_NAME` | `teslamate` | Database name |
| `ENCRYPTION_KEY` | *(required)* | TeslaMate ENCRYPTION_KEY (for Owner API tokens) |

### Vehicle

| Variable | Default | Description |
|----------|---------|-------------|
| `TESLA_CAR_ID` | `1` | TeslaMate car ID |
| `TESLA_BATTERY_KWH` | `75` | Usable battery capacity in kWh |
| `TESLA_BATTERY_RANGE_KM` | `525` | EPA range at 100% in km |

| Vehicle | Battery (kWh) | Range (km) |
|---------|--------------|------------|
| Model 3 Standard Range | 54 | 350 |
| Model 3 Long Range | 75 | 500 |
| Model Y Long Range | 75 | 525 |
| Model S Long Range | 100 | 650 |
| Model X Long Range | 100 | 560 |

### Cost Defaults

| Variable | Default | Description |
|----------|---------|-------------|
| `TESLA_ELECTRICITY_RATE` | `0.12` | Electricity cost in $/kWh |
| `TESLA_GAS_PRICE` | `3.50` | Gas price in $/gallon |
| `TESLA_GAS_MPG` | `28` | Comparable gas vehicle MPG |

### TPMS (Optional)

| Variable | Default | Description |
|----------|---------|-------------|
| `TESLA_TPMS_MIN_THRESHOLD` | `2.0` | Low pressure warning (bar) |
| `TESLA_TPMS_MAX_THRESHOLD` | `2.5` | High pressure warning (bar) |

## Architecture

Single-file Python server using **FastMCP**. Two data paths:

```
┌─────────────┐     ┌──────────────┐
│  TeslaMate   │────▶│   Postgres   │──┐
│  (logger)    │     │  (telemetry) │  │   ┌───────────┐     ┌────────────┐
└─────────────┘     └──────────────┘  ├──▶│ tesla.py  │────▶│ MCP Client │
                                       │   │ (server)  │     │ (Claude,   │
┌─────────────┐     ┌──────────────┐  │   └───────────┘     │  OpenClaw) │
│  Tesla       │────▶│ Owner API    │──┘                     └────────────┘
│  Owner API   │     │ (tokens from │
└─────────────┘     │  TeslaMate)  │
                    └──────────────┘
```

## GitHub Actions

Docker images are built and pushed to GitHub Container Registry on each version tag:

```bash
git tag v0.1.0
git push origin v0.1.0
```

## Limitations

- **Single vehicle** — queries use a configurable `car_id`
- **Imperial units** — output is in miles, °F, and PSI
- **Estimated kWh** — energy estimated from ideal range deltas (~90-95% accurate)

## License

MIT
