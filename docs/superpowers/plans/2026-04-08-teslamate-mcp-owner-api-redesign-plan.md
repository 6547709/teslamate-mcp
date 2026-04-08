# TeslaMate MCP Owner API Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Fleet API with Owner API (read from TeslaMate DB), remove all command tools, add 4 enhanced features, Dockerize with GitHub Actions.

**Architecture:**
- Single-file `tesla.py` (1502 lines) refactored to support Owner API token decryption from TeslaMate PostgreSQL
- Token acquisition: read encrypted tokens from TeslaMate `tokens` table, decrypt with ENCRYPTION_KEY (AES-256-GCM), use Owner API endpoints
- Enhanced features implemented as new FastMCP tools
- Docker image built via GitHub Actions, published to GHCR

**Tech Stack:** Python 3.10+, FastMCP 2.0, httpx, psycopg2-binary, cryptography (for AES-GCM)

---

## File Structure

```
teslamate-mcp/
├── tesla.py                          # Main (refactored)
├── pyproject.toml                    # Updated description + cryptography dep
├── Dockerfile                        # New
├── .github/
│   └── workflows/
│       └── docker.yml                # New — build & push on tag
├── docker-compose snippet             # docs/deployment/docker-compose.yml (new)
├── README.md                         # Updated
└── docs/superpowers/specs/
    └── 2026-04-08-teslamate-mcp-owner-api-redesign.md  # (already exists)
```

---

## Task 1: Owner API Token Decryption

**Files:**
- Modify: `tesla.py:1-100` (env vars + header docstring)
- Modify: `tesla.py:168-230` (token management — replace Fleet API with Owner API from DB)
- Add: `tesla.py` — new `_decrypt_tokens()` and `_owner_api_get()` functions
- Add: `pyproject.toml` — add `cryptography` dependency

**Steps:**

- [ ] **Step 1: Add cryptography dependency**

```bash
# pyproject.toml — add to dependencies:
"cryptography>=42.0",
```

Run: `pip install cryptography httpx psycopg2-binary fastmcp`

- [ ] **Step 2: Add ENCRYPTION_KEY env var + remove Fleet API vars**

In `tesla.py`, replace the config block (lines ~100-136):

```python
# TeslaMate Postgres (read-only telemetry)
DB_HOST = os.environ.get("TESLAMATE_DB_HOST", "")
DB_PORT = int(os.environ.get("TESLAMATE_DB_PORT", "5432"))
DB_USER = os.environ.get("TESLAMATE_DB_USER", "teslamate")
DB_PASS = os.environ.get("TESLAMATE_DB_PASS", "")
DB_NAME = os.environ.get("TESLAMATE_DB_NAME", "teslamate")

# Encryption key (same as TeslaMate's ENCRYPTION_KEY)
ENCRYPTION_KEY = os.environ.get("ENCRYPTION_KEY", "")
if not ENCRYPTION_KEY:
    raise RuntimeError("ENCRYPTION_KEY environment variable is required")

# Owner API (read from TeslaMate DB — no file, no manual refresh)
OWNER_API_URL = "https://owner-api.tesla.com"
HAS_OWNER_API = bool(DB_HOST and DB_PASS and ENCRYPTION_KEY)

# Vehicle-specific
CAR_ID = int(os.environ.get("TESLA_CAR_ID", "1"))
# ... rest unchanged (BATTERY_KWH, BATTERY_RANGE_KM, ELECTRICITY_RATE, GAS_PRICE, GAS_MPG)
```

- [ ] **Step 3: Implement AES-256-GCM token decryption**

Add after the rate limiting section (~line 166):

```python
# -- Owner API Token Decryption -----------------------------------------------

import base64
import hashlib
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_cached_owner_token: dict | None = None


def _decrypt_tokens() -> dict:
    """Read and decrypt Owner API tokens from TeslaMate PostgreSQL.

    Tokens are stored encrypted in the 'tokens' table using AES-256-GCM.
    The ENCRYPTION_KEY is hashed with SHA256 to produce the AES key.
    """
    global _cached_owner_token

    if _cached_owner_token:
        return _cached_owner_token

    if not HAS_OWNER_API:
        raise RuntimeError(
            "Owner API not configured. "
            "Set TESLAMATE_DB_HOST, TESLAMATE_DB_PASS, and ENCRYPTION_KEY."
        )

    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT access, refresh FROM tokens LIMIT 1")
            row = cur.fetchone()
            if not row:
                raise RuntimeError("No tokens found in TeslaMate database.")
            encrypted_access = row[0]
            encrypted_refresh = row[1]
    finally:
        conn.close()

    # Derive AES-256 key from ENCRYPTION_KEY
    key = hashlib.sha256(ENCRYPTION_KEY.encode()).digest()
    aesgcm = AESGCM(key)

    def decrypt(encrypted_token: str) -> str:
        if not encrypted_token:
            return ""
        # Ciphertext format: | IV (12 bytes) | Ciphertag (16 bytes) | Ciphertext |
        data = base64.b64decode(encrypted_token)
        iv = data[:12]
        ciphertext = data[12:]
        return aesgcm.decrypt(iv, ciphertext, None).decode()

    _cached_owner_token = {
        "access": decrypt(encrypted_access),
        "refresh": decrypt(encrypted_refresh),
    }
    return _cached_owner_token
```

- [ ] **Step 4: Replace Fleet API token logic**

Replace `_get_access_token()` (lines 174-230) with:

```python
def _get_access_token() -> str:
    """Get a valid Owner API access token from TeslaMate database."""
    tokens = _decrypt_tokens()
    return tokens.get("access", "")
```

- [ ] **Step 5: Add Owner API GET helper**

Add after `_decrypt_tokens()`:

```python
async def _owner_api_get(path: str) -> dict:
    """GET from Tesla Owner API using tokens from TeslaMate DB."""
    if not HAS_OWNER_API:
        raise RuntimeError("Owner API not configured.")
    token = _get_access_token()
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{OWNER_API_URL}{path}",
            headers={"Authorization": f"Bearer {token}"},
        )
        resp.raise_for_status()
        return resp.json()
```

- [ ] **Step 6: Update header docstring**

Replace the file header docstring to reflect the new architecture:

```python
"""Tesla MCP Server — TeslaMate analytics + Owner API real-time data.

Single-file FastMCP server. Stdio transport. Reads from TeslaMate PostgreSQL
database and Tesla Owner API (tokens shared with TeslaMate, encrypted).

Two data paths:
  1. TeslaMate Postgres (read-only) — historical telemetry and analytics
  2. Tesla Owner API (read-only) — live vehicle data via TeslaMate tokens
...
```

- [ ] **Step 7: Commit**

```bash
git add tesla.py pyproject.toml
git commit -m "feat: replace Fleet API with Owner API token decryption from TeslaMate DB"
```

---

## Task 2: Refactor tesla_live for Owner API

**Files:**
- Modify: `tesla.py:852-933` (tesla_live function)

**Steps:**

- [ ] **Step 1: Refactor tesla_live to use Owner API**

Replace the `tesla_live` function (lines 852-933):

```python
@mcp.tool()
async def tesla_live() -> str:
    """Live vehicle data from Tesla Owner API — real-time battery, charging, climate.

    Uses tokens shared with TeslaMate (decrypted from DB). More current than
    TeslaMate which polls on intervals.
    """
    if not HAS_OWNER_API:
        return "Owner API not configured. Set ENCRYPTION_KEY and TeslaMate DB env vars."

    # Get vehicle list to find vehicle_id
    vehicles_resp = await _owner_api_get("/api/1/vehicles")
    vehicles = vehicles_resp.get("response", [])
    if not vehicles:
        return "No vehicles found."

    # Find the first vehicle (or filter by CAR_ID)
    vehicle = vehicles[0]
    vehicle_id = vehicle.get("id")

    # Get live vehicle data
    data = await _owner_api_get(f"/api/1/vehicles/{vehicle_id}/vehicle_data")
    r = data.get("response", {})
    cs = r.get("charge_state", {})
    cl = r.get("climate_state", {})
    vs = r.get("vehicle_state", {})
    ds = r.get("drive_state", {})

    # ... rest of formatting code stays the same as existing tesla_live ...
    # (copy the existing response formatting lines 872-933)
```

- [ ] **Step 2: Commit**

```bash
git add tesla.py
git commit -m "feat: migrate tesla_live from Fleet API to Owner API"
```

---

## Task 3: Remove All Command Tools

**Files:**
- Modify: `tesla.py` — remove Fleet API command functions and tool registrations

**Steps:**

- [ ] **Step 1: Identify and remove command tools**

In `tesla.py`, locate and remove:
- `_check_rate_limit()` and `_log_command()` (lines 148-165)
- `_fleet_command()` function (lines 253-291)
- All `@mcp.tool()` decorated command functions (climate_on, climate_off, set_temp, charge_start, charge_stop, set_charge_limit, lock, unlock, honk, flash, trunk, sentry)
- The command-related env vars: `PROXY_URL`, `FLEET_URL`, `VIN`, `TOKEN_FILE`, `CLIENT_ID`, `CLIENT_SECRET`, `VERIFY_SSL` and `HAS_PROXY`

- [ ] **Step 2: Update header docstring**

Remove command tool descriptions from the header docstring.

- [ ] **Step 3: Commit**

```bash
git add tesla.py
git commit -m "feat: remove all vehicle command tools (Fleet API no longer used)"
```

---

## Task 4: Add Enhanced Feature — Driving Score

**Files:**
- Add: `tesla.py` — new `tesla_driving_score` tool

**Steps:**

- [ ] **Step 1: Add tesla_driving_score tool**

Add after the existing `tesla_drives` function:

```python
@mcp.tool()
async def tesla_driving_score(
    period: str = "recent_n",
    n: int = 10,
    year: int | None = None,
    month: int | None = None,
) -> str:
    """Driving score based on acceleration, braking, and speed habits.

    Args:
        period: "recent_n" (default), "monthly", or "yearly"
        n: Number of recent drives to score (default: 10, used when period="recent_n")
        year: Year for monthly/yearly period
        month: Month (1-12) for monthly period
    """
    # Build date filter
    if period == "recent_n":
        rows = _query(
            f"""
            SELECT d.distance, d.duration_min, d.power_max, d.power_min,
                   d.speed_max, d.start_date
            FROM drives d
            WHERE d.car_id = %s AND d.distance > 0
            ORDER BY d.start_date DESC LIMIT %s
            """,
            (CAR_ID, n),
        )
        label = f"last {len(rows)} drives"
    elif period == "monthly":
        if not year or not month:
            return "year and month are required for monthly period"
        start = datetime(year, month, 1)
        if month == 12:
            end = datetime(year + 1, 1, 1)
        else:
            end = datetime(year, month + 1, 1)
        rows = _query(
            f"""
            SELECT d.distance, d.duration_min, d.power_max, d.power_min,
                   d.speed_max, d.start_date
            FROM drives d
            WHERE d.car_id = %s AND d.distance > 0
              AND d.start_date >= %s AND d.start_date < %s
            ORDER BY d.start_date DESC
            """,
            (CAR_ID, start.isoformat(), end.isoformat()),
        )
        label = f"{year}-{month:02d}"
    elif period == "yearly":
        if not year:
            return "year is required for yearly period"
        start = datetime(year, 1, 1)
        end = datetime(year + 1, 1, 1)
        rows = _query(
            f"""
            SELECT d.distance, d.duration_min, d.power_max, d.power_min,
                   d.speed_max, d.start_date
            FROM drives d
            WHERE d.car_id = %s AND d.distance > 0
              AND d.start_date >= %s AND d.start_date < %s
            ORDER BY d.start_date DESC
            """,
            (CAR_ID, start.isoformat(), end.isoformat()),
        )
        label = str(year)
    else:
        return f"Unknown period: {period}. Use recent_n, monthly, or yearly."

    if not rows:
        return f"No drives found for {label}."

    # Score calculation
    POWER_ACCEL_THRESHOLD = 50   # kW — above this = aggressive acceleration
    POWER_BRAKE_THRESHOLD = -30  # kW — below this = harsh braking
    SPEED_THRESHOLD_KMH = 130     # km/h — above this = speeding

    score = 100
    details = []

    for r in rows:
        power_max = r.get("power_max") or 0
        power_min = r.get("power_min") or 0
        speed_max = r.get("speed_max") or 0
        dist_km = r.get("distance") or 0

        if power_max > POWER_ACCEL_THRESHOLD:
            deduct = min(5, round((power_max - POWER_ACCEL_THRESHOLD) / 10))
            score -= deduct
            details.append(f"hard accel ({power_max:.0f} kW)")

        if power_min < POWER_BRAKE_THRESHOLD:
            deduct = min(5, round((abs(power_min) - abs(POWER_BRAKE_THRESHOLD)) / 10))
            score -= deduct
            details.append(f"hard brake ({power_min:.0f} kW)")

        if speed_max > SPEED_THRESHOLD_KMH:
            deduct = min(3, round((speed_max - SPEED_THRESHOLD_KMH) / 20))
            score -= deduct
            details.append(f"high speed ({speed_max:.0f} km/h)")

    score = max(0, min(100, score))

    lines = [f"**Driving Score — {label}**\n"]
    lines.append(f"Score: {score}/100")
    if details:
        lines.append(f"Events: {', '.join(details[:5])}")
    lines.append(f"Drives analyzed: {len(rows)}")
    return "\n".join(lines)
```

- [ ] **Step 2: Commit**

```bash
git add tesla.py
git commit -m "feat: add tesla_driving_score tool"
```

---

## Task 5: Add Enhanced Feature — Trip Classification

**Files:**
- Add: `tesla.py` — new `tesla_trips_by_category` and `tesla_trip_categories` tools

**Steps:**

- [ ] **Step 1: Add trip classification logic and tools**

Add after `tesla_driving_score`:

```python
# -- Trip Classification Logic -----------------------------------------------

TRIP_THRESHOLD_KM = 100  # drives longer than this = "long_trip"
COMMUTE_PAIRS = [
    ("home", "work"),
    ("work", "home"),
]


def _classify_trip(start_geofence: str | None, end_geofence: str | None, distance_km: float) -> str:
    """Classify a trip based on geofence names and distance."""
    start = (start_geofence or "").lower()
    end = (end_geofence or "").lower()

    # Long trip check first
    if distance_km > TRIP_THRESHOLD_KM:
        return "long_trip"

    # Commute: home <-> work
    for home_key, work_key in COMMUTE_PAIRS:
        if (home_key in start and work_key in end) or (home_key in end and work_key in start):
            return "commute"

    # Shopping keywords
    shopping_keywords = ["mall", "store", "shop", "market", "supermarket", "grocery"]
    if any(kw in start or kw in end for kw in shopping_keywords):
        return "shopping"

    # Leisure keywords
    leisure_keywords = ["park", "beach", "restaurant", "cafe", "movie", "gym", "playground"]
    if any(kw in start or kw in end for kw in leisure_keywords):
        return "leisure"

    return "other"


@mcp.tool()
async def tesla_trips_by_category(category: str = "commute", limit: int = 20) -> str:
    """Get trips filtered by category.

    Args:
        category: "commute", "shopping", "leisure", "long_trip", or "other"
        limit: Max trips to return (default: 20)
    """
    rows = _query(
        f"""
        SELECT d.start_date, d.distance, d.duration_min,
               sa.display_name AS start_location,
               ea.display_name AS end_location
        FROM drives d
        LEFT JOIN addresses sa ON d.start_address_id = sa.id
        LEFT JOIN addresses ea ON d.end_address_id = ea.id
        WHERE d.car_id = %s AND d.distance > 0
        ORDER BY d.start_date DESC LIMIT %s
        """,
        (CAR_ID, limit * 3),  # fetch extra, filter after
    )

    classified = []
    for r in rows:
        dist_km = r.get("distance") or 0
        cat = _classify_trip(
            r.get("start_location"),
            r.get("end_location"),
            dist_km,
        )
        if cat == category:
            classified.append(r)
        if len(classified) >= limit:
            break

    if not classified:
        return f"No {category} trips found."

    lines = [f"**{category.upper()} Trips** ({len(classified)} results)\n"]
    for r in classified:
        date = str(r.get("start_date", ""))[:16]
        dist_mi = _km_to_mi(r.get("distance") or 0)
        dur = r.get("duration_min") or 0
        start = r.get("start_location") or "?"
        end = r.get("end_location") or "?"
        lines.append(f"- {date}: {dist_mi} mi, {dur} min, {start} → {end}")
    return "\n".join(lines)


@mcp.tool()
async def tesla_trip_categories() -> str:
    """Show count of trips by category for recent drives."""
    rows = _query(
        f"""
        SELECT d.distance,
               sa.display_name AS start_location,
               ea.display_name AS end_location
        FROM drives d
        LEFT JOIN addresses sa ON d.start_address_id = sa.id
        LEFT JOIN addresses ea ON d.end_address_id = ea.id
        WHERE d.car_id = %s AND d.distance > 0
        ORDER BY d.start_date DESC LIMIT 100
        """,
        (CAR_ID,),
    )

    counts = {"commute": 0, "shopping": 0, "leisure": 0, "long_trip": 0, "other": 0}
    for r in rows:
        cat = _classify_trip(
            r.get("start_location"),
            r.get("end_location"),
            r.get("distance") or 0,
        )
        counts[cat] += 1

    total = sum(counts.values())
    lines = ["**Trip Categories** (last 100 drives)\n"]
    for cat, cnt in sorted(counts.items(), key=lambda x: -x[1]):
        pct = round(cnt / total * 100) if total > 0 else 0
        lines.append(f"- {cat}: {cnt} ({pct}%)")
    return "\n".join(lines)
```

- [ ] **Step 2: Commit**

```bash
git add tesla.py
git commit -m "feat: add trip classification tools"
```

---

## Task 6: Add Enhanced Feature — Monthly Report

**Files:**
- Modify: `tesla.py` — replace/improve existing `tesla_monthly_summary` with `tesla_monthly_report`

**Steps:**

- [ ] **Step 1: Add tesla_monthly_report tool**

Add after `tesla_trip_categories`:

```python
@mcp.tool()
async def tesla_monthly_report(year: int, month: int) -> str:
    """Monthly driving report with stats and comparison to previous month.

    Args:
        year: Year (e.g., 2026)
        month: Month (1-12)
    """
    start = datetime(year, month, 1)
    if month == 12:
        prev_start = datetime(year, 11, 1)
        next_start = datetime(year + 1, 1, 1)
    else:
        prev_start = datetime(year, month - 1, 1)
        next_start = datetime(year, month + 1, 1)

    # Current month data
    rows = _query(
        f"""
        SELECT COUNT(*) AS trips,
               COALESCE(SUM(distance), 0) AS total_km,
               COALESCE(SUM(GREATEST(start_ideal_range_km - end_ideal_range_km, 0)
                   * {KWH_PER_KM}), 0) AS total_kwh,
               COALESCE(SUM(duration_min), 0) AS total_min
        FROM drives
        WHERE car_id = %s AND distance > 0
          AND start_date >= %s AND start_date < %s
        """,
        (CAR_ID, start.isoformat(), next_start.isoformat()),
    )
    r = rows[0] if rows else {}

    trips = r.get("trips") or 0
    km = r.get("total_km") or 0
    kwh = r.get("total_kwh") or 0
    minutes = r.get("total_min") or 0
    mi = round(km * 0.621371)
    wh_mi = round(kwh * 1000 / (km * 0.621371)) if km > 0 else 0
    cost = round(kwh * ELECTRICITY_RATE, 2)

    # Previous month for comparison
    prev_rows = _query(
        f"""
        SELECT COALESCE(SUM(distance), 0) AS total_km,
               COALESCE(SUM(GREATEST(start_ideal_range_km - end_ideal_range_km, 0)
                   * {KWH_PER_KM}), 0) AS total_kwh
        FROM drives
        WHERE car_id = %s AND distance > 0
          AND start_date >= %s AND start_date < %s
        """,
        (CAR_ID, prev_start.isoformat(), start.isoformat()),
    )
    prev_r = prev_rows[0] if prev_rows else {}
    prev_km = prev_r.get("total_km") or 0
    prev_kwh = prev_r.get("total_kwh") or 0

    lines = [f"**Monthly Report — {year}-{month:02d}**\n"]
    lines.append(f"Trips: {trips}")
    lines.append(f"Distance: {mi} mi ({km:.1f} km)")
    lines.append(f"Energy: {kwh:.1f} kWh")
    lines.append(f"Avg efficiency: {wh_mi} Wh/mi")
    lines.append(f"Est. cost: ${cost}")
    lines.append(f"Time driving: {minutes} min")

    if prev_km > 0:
        dist_delta = round((km - prev_km) / prev_km * 100)
        eff_delta = round((kwh - prev_kwh) / prev_kwh * 100) if prev_kwh > 0 else 0
        lines.append(f"\nvs prev month: distance {dist_delta:+d}%, energy {eff_delta:+d}%")

    return "\n".join(lines)
```

- [ ] **Step 2: Commit**

```bash
git add tesla.py
git commit -m "feat: add tesla_monthly_report with month-over-month comparison"
```

---

## Task 7: Add Enhanced Feature — TPMS Monitoring

**Files:**
- Add: `tesla.py` — new `tesla_tpms_status` and `tesla_tpms_history` tools

**Steps:**

- [ ] **Step 1: Add TPMS config and tools**

Add to config section:

```python
# TPMS thresholds (bar)
TPMS_MIN = float(os.environ.get("TESLA_TPMS_MIN_THRESHOLD", "2.0"))
TPMS_MAX = float(os.environ.get("TESLA_TPMS_MAX_THRESHOLD", "2.5"))
TPMS_WARN_DELTA = 0.15  # bar — warn if any tire differs by this much from others
```

Add after `tesla_monthly_report`:

```python
@mcp.tool()
async def tesla_tpms_status() -> str:
    """Current TPMS pressures with warnings for anomalies.

    Warns if any tire is below TESLA_TPMS_MIN_THRESHOLD or above
    TESLA_TPMS_MAX_THRESHOLD, or if any tire differs from the average by > 0.15 bar.
    """
    if not HAS_OWNER_API:
        return "Owner API not configured."

    vehicles_resp = await _owner_api_get("/api/1/vehicles")
    vehicles = vehicles_resp.get("response", [])
    if not vehicles:
        return "No vehicles found."
    vehicle_id = vehicles[0].get("id")

    data = await _owner_api_get(f"/api/1/vehicles/{vehicle_id}/vehicle_data")
    vs = data.get("response", {}).get("vehicle_state", {})

    positions = [("fl", "Front Left"), ("fr", "Front Right"),
                 ("rl", "Rear Left"), ("rr", "Rear Right")]
    pressures = {}
    lines = ["**TPMS Status**\n"]

    for pos, label in positions:
        bar = vs.get(f"tpms_pressure_{pos}")
        if bar is None:
            lines.append(f"{label}: N/A")
            continue
        psi = round(bar * 14.5038, 1)
        status = "OK"
        if bar < TPMS_MIN:
            status = f"LOW (< {TPMS_MIN} bar)"
        elif bar > TPMS_MAX:
            status = f"HIGH (> {TPMS_MAX} bar)"
        soft = vs.get(f"tpms_soft_warning_{pos}")
        if soft:
            status = "SOFT WARNING"
        pressures[pos] = bar
        lines.append(f"{label}: {psi} PSI ({bar:.2f} bar) — {status}")

    # Check consistency
    if len(pressures) >= 3:
        vals = list(pressures.values())
        avg = sum(vals) / len(vals)
        for pos, bar in pressures.items():
            if abs(bar - avg) > TPMS_WARN_DELTA:
                label = dict(positions).get(pos, pos)
                lines.append(f"  ⚠ {label} deviates {abs(bar-avg):.2f} bar from average")
        lines.append(f"Average: {round(avg*14.5038,1)} PSI ({round(avg,2)} bar)")

    return "\n".join(lines)


@mcp.tool()
async def tesla_tpms_history(days: int = 30) -> str:
    """Recent TPMS pressure history from TeslaMate.

    Shows the average and min/max pressures recorded in positions table.
    Note: TeslaMate only stores positions during drives/charging, not while parked.

    Args:
        days: Number of days to look back (default: 30)
    """
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    rows = _query(
        f"""
        SELECT date,
               tpms_pressure_fl, tpms_pressure_fr,
               tpms_pressure_rl, tpms_pressure_rr
        FROM positions
        WHERE car_id = %s AND date >= %s
          AND (tpms_pressure_fl IS NOT NULL OR tpms_pressure_fr IS NOT NULL)
        ORDER BY date DESC
        LIMIT 20
        """,
        (CAR_ID, cutoff),
    )

    if not rows:
        return f"No TPMS data in the last {days} days."

    lines = [f"**TPMS History** (last {days} days, {len(rows)} records)\n"]
    for r in rows:
        date = str(r.get("date", ""))[:16]
        fl = r.get("tpms_pressure_fl")
        fr = r.get("tpms_pressure_fr")
        rl = r.get("tpms_pressure_rl")
        rr = r.get("tpms_pressure_rr")
        fl_s = f"{round(fl*14.5038,1)}" if fl else "—"
        fr_s = f"{round(fr*14.5038,1)}" if fr else "—"
        rl_s = f"{round(rl*14.5038,1)}" if rl else "—"
        rr_s = f"{round(rr*14.5038,1)}" if rr else "—"
        lines.append(f"{date}: FL={fl_s} FR={fr_s} RL={rl_s} RR={rr_s} PSI")
    return "\n".join(lines)
```

- [ ] **Step 2: Commit**

```bash
git add tesla.py
git commit -m "feat: add TPMS monitoring tools"
```

---

## Task 8: Docker Setup

**Files:**
- Create: `Dockerfile`
- Create: `docs/deployment/docker-compose.yml`
- Create: `.dockerignore`

**Steps:**

- [ ] **Step 1: Create Dockerfile**

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --no-cache-dir -e .

COPY tesla.py ./

ENTRYPOINT ["mcp-teslamate-fleet"]
```

- [ ] **Step 2: Create .dockerignore**

```
__pycache__
*.pyc
.git
.github
*.egg-info
.eggs
```

- [ ] **Step 3: Create deployment docs**

Create `docs/deployment/docker-compose.yml`:

```yaml
# TeslaMate MCP — Docker Compose snippet
# Add this to your existing teslamate docker-compose.yml
# TeslaMate must already be running with ENCRYPTION_KEY configured

services:
  teslamate-mcp:
    image: ghcr.io/<YOUR-GITHUB-USERNAME>/teslamate-mcp:latest
    restart: always
    environment:
      - ENCRYPTION_KEY=<your-teslamate-encryption-key>
      - DATABASE_HOST=database
      - DATABASE_PORT=5432
      - DATABASE_USER=teslamate
      - DATABASE_PASS=secret
      - DATABASE_NAME=teslamate
      - TESLA_CAR_ID=1
      - TESLA_BATTERY_KWH=75
      - TESLA_BATTERY_RANGE_KM=525
      - TESLA_ELECTRICITY_RATE=0.12
      - TESLA_GAS_PRICE=3.50
      - TESLA_GAS_MPG=28
      # Optional TPMS thresholds
      # - TESLA_TPMS_MIN_THRESHOLD=2.0
      # - TESLA_TPMS_MAX_THRESHOLD=2.5
    depends_on:
      - database
```

- [ ] **Step 4: Commit**

```bash
git add Dockerfile .dockerignore docs/deployment/docker-compose.yml
git commit -m "feat: add Dockerfile and deployment config"
```

---

## Task 9: GitHub Actions

**Files:**
- Create: `.github/workflows/docker.yml`

**Steps:**

- [ ] **Step 1: Create GitHub Actions workflow**

```yaml
name: Build and Push Docker Image

on:
  push:
    tags:
      - 'v*'

jobs:
  docker:
    runs-on: ubuntu-latest
    permissions:
      packages: write

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      - name: Log in to GHCR
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Extract metadata
        id: meta
        uses: docker/metadata-action@v5
        with:
          images: ghcr.io/${{ github.repository }}
          tags: |
            type=semver,pattern={{version}}
            type=semver,pattern={{major}}.{{minor}}
            type=sha

      - name: Build and push
        uses: docker/build-push-action@v5
        with:
          context: .
          push: true
          tags: ${{ steps.meta.outputs.tags }}
          platforms: linux/amd64,linux/arm64
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/docker.yml
git commit -m "ci: add Docker build and push workflow on tag"
```

---

## Task 10: Documentation

**Files:**
- Modify: `README.md`
- Modify: `pyproject.toml` (description)

**Steps:**

- [ ] **Step 1: Update README.md**

Update the README to reflect:
- New name: `teslamate-mcp` (not `mcp-teslamate-fleet`)
- Owner API (not Fleet API)
- Remove all command tool references
- Add the 4 new enhanced features
- Add deployment instructions with docker-compose snippet
- Add GitHub Actions badge

- [ ] **Step 2: Update pyproject.toml description**

```toml
description = "MCP server for TeslaMate analytics + Owner API real-time data"
```

- [ ] **Step 3: Commit**

```bash
git add README.md pyproject.toml
git commit -m "docs: update README and description"
```

---

## Spec Coverage Check

- [ ] Owner API token decryption from TeslaMate DB — Task 1
- [ ] tesla_live with Owner API — Task 2
- [ ] Remove command tools — Task 3
- [ ] tesla_driving_score — Task 4
- [ ] tesla_trips_by_category + tesla_trip_categories — Task 5
- [ ] tesla_monthly_report — Task 6
- [ ] tesla_tpms_status + tesla_tpms_history — Task 7
- [ ] Dockerfile + docker-compose — Task 8
- [ ] GitHub Actions — Task 9
- [ ] Documentation — Task 10

**All spec requirements covered.**

---

## Post-Implementation Checklist

- [ ] Run `pytest` if tests exist
- [ ] Test `tesla_live` with real Owner API tokens from TeslaMate DB
- [ ] Test `tesla_driving_score` with `period="recent_n"` and `period="monthly"`
- [ ] Test `tesla_trips_by_category` and `tesla_trip_categories`
- [ ] Test `tesla_monthly_report` with current month
- [ ] Test `tesla_tpms_status` (needs real vehicle data)
- [ ] Build Docker image locally and verify
- [ ] Create first Git tag and verify GHCR push works
- [ ] Verify docker-compose deployment on NAS
