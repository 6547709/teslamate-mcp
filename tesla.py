"""Tesla MCP Server -- TeslaMate analytics + Owner API real-time data.

See README.md (English) or README_zh.md for full documentation."""

Single-file FastMCP server. Stdio transport. Works with TeslaMate, Owner API,
or both -- tools are available based on which backends you configure.

Two data paths:
  1. TeslaMate Postgres (read-only) -- historical telemetry and analytics
  2. Tesla Owner API (read-only live data from TeslaMate DB)

Read tools (TeslaMate):
  tesla_status            -- Current vehicle state (battery, range, location, climate)
  tesla_charging_history  -- Charging sessions over N days
  tesla_drives            -- Recent drives with distance, duration, efficiency
  tesla_battery_health    -- Battery degradation trend
  tesla_efficiency        -- Wh/mi consumption trends
  tesla_location_history  -- Where the car has been, time at each location
  tesla_state_history     -- Vehicle state transitions (online/asleep/offline)
  tesla_software_updates  -- Firmware version history

Analytics tools (TeslaMate):
  tesla_savings           -- Gas savings scorecard
  tesla_trip_cost         -- Estimate trip cost to a destination
  tesla_efficiency_by_temp -- Efficiency curve by temperature
  tesla_charging_by_location -- Charging patterns by location
  tesla_top_destinations  -- Most visited locations
  tesla_longest_trips     -- Top drives ranked by distance
  tesla_monthly_summary   -- Monthly driving summary
  tesla_vampire_drain     -- Battery loss while parked

Live data tool (Owner API):
  tesla_live              -- Real-time vehicle data from Owner API

Environment variables:
  # TeslaMate Postgres
  TESLAMATE_DB_HOST     -- Postgres host (e.g. localhost, 192.168.1.50)
  TESLAMATE_DB_PORT     -- Postgres port (default: 5432)
  TESLAMATE_DB_USER     -- Postgres user (default: teslamate)
  TESLAMATE_DB_PASS     -- Postgres password
  TESLAMATE_DB_NAME     -- Postgres database (default: teslamate)

  # Encryption key (TeslaMate's ENCRYPTION_KEY -- required for Owner API)
  ENCRYPTION_KEY        -- AES-256 key used to decrypt tokens from DB

  # Vehicle config
  TESLA_CAR_ID          -- TeslaMate car ID (default: 1)
  TESLA_BATTERY_KWH     -- Usable battery capacity in kWh (default: 75)
  TESLA_BATTERY_RANGE_KM -- EPA range at 100% in km (default: 525)

  # Cost defaults (overridable per-tool-call)
  TESLA_ELECTRICITY_RATE_USD -- USD/kWh (default: 0.12)
  TESLA_ELECTRICITY_RATE_RMB -- Electricity cost in RMB/kWh (default: 0.6)
  TESLA_GAS_PRICE        -- USD/gallon for comparison (default: 3.50)
  TESLA_GAS_MPG          -- Comparable gas vehicle MPG (default: 28)

  # Units (metric)
  USE_METRIC_UNITS       -- Set "true" for km, degC, kWh/100km, JPY (default: false/imperial)
"""

from __future__ import annotations

import base64
import hashlib
import math
import os
from datetime import datetime, timedelta
from decimal import Decimal

import httpx
import psycopg2
import psycopg2.extras
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastmcp import FastMCP

# -- Configuration ------------------------------------------------------------

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

# Owner API (read from TeslaMate DB -- no file, no manual refresh)
OWNER_API_URL = "https://owner-api.tesla.com"
HAS_OWNER_API = bool(DB_HOST and DB_PASS and ENCRYPTION_KEY)

# Vehicle-specific
CAR_ID = int(os.environ.get("TESLA_CAR_ID", "1"))
BATTERY_KWH = float(os.environ.get("TESLA_BATTERY_KWH", "75"))
BATTERY_RANGE_KM = float(os.environ.get("TESLA_BATTERY_RANGE_KM", "525"))
KWH_PER_KM = BATTERY_KWH / BATTERY_RANGE_KM

# Cost defaults
ELECTRICITY_RATE_RMB = float(os.environ.get("TESLA_ELECTRICITY_RATE_RMB", "0.6"))  # RMB/kWh
ELECTRICITY_RATE = float(os.environ.get("TESLA_ELECTRICITY_RATE_USD", "0.12"))    # USD/kWh (fallback)
GAS_PRICE = float(os.environ.get("TESLA_GAS_PRICE", "3.50"))
GAS_MPG = int(os.environ.get("TESLA_GAS_MPG", "28"))

# Units: true = metric (km, degC, kWh/100km), false = imperial (mi, degF, Wh/mi)
USE_METRIC_UNITS = os.environ.get("USE_METRIC_UNITS", "false").lower() in ("true", "1", "yes")

# TPMS thresholds (bar)
TPMS_MIN = float(os.environ.get("TESLA_TPMS_MIN_THRESHOLD", "2.0"))
TPMS_MAX = float(os.environ.get("TESLA_TPMS_MAX_THRESHOLD", "2.5"))
TPMS_WARN_DELTA = 0.15  # bar -- warn if any tire differs from average by this much

# Backend availability
HAS_TESLAMATE = bool(DB_HOST and DB_PASS)

# HTTP server mode (for containerized deployment)
HTTP_HOST = os.environ.get("HTTP_HOST", "0.0.0.0")
HTTP_PORT = int(os.environ.get("HTTP_PORT", "8080"))
MCP_TRANSPORT = os.environ.get("MCP_TRANSPORT", "stdio")  # "stdio" or "streamable-http"

# -- Query limits (set to -1 for no limit) ------------------------------------
def _limit_sql(raw_limit: int | None) -> str:
    """Return SQL LIMIT clause; -1 means no limit."""
    if raw_limit is None or raw_limit < 0:
        return ""
    return f"LIMIT {raw_limit}"

LIMIT_DRIVES             = int(os.environ.get("TESLA_LIMIT_DRIVES", "50"))
LIMIT_CHARGING           = int(os.environ.get("TESLA_LIMIT_CHARGING", "50"))
LIMIT_TRIP_CATEGORIES    = int(os.environ.get("TESLA_LIMIT_TRIP_CATEGORIES", "100"))
LIMIT_BATTERY_HEALTH     = int(os.environ.get("TESLA_LIMIT_BATTERY_HEALTH", "24"))
LIMIT_BATTERY_SAMPLES    = int(os.environ.get("TESLA_LIMIT_BATTERY_SAMPLES", "20"))
LIMIT_LOCATION_HISTORY   = int(os.environ.get("TESLA_LIMIT_LOCATION_HISTORY", "20"))
LIMIT_STATE_HISTORY      = int(os.environ.get("TESLA_LIMIT_STATE_HISTORY", "100"))
LIMIT_SOFTWARE_UPDATES   = int(os.environ.get("TESLA_LIMIT_SOFTWARE_UPDATES", "20"))
LIMIT_CHARGING_BY_LOC    = int(os.environ.get("TESLA_LIMIT_CHARGING_BY_LOCATION", "15"))
LIMIT_TPMS_HISTORY       = int(os.environ.get("TESLA_LIMIT_TPMS_HISTORY", "20"))
LIMIT_VAMPIRE_DRAIN      = int(os.environ.get("TESLA_LIMIT_VAMPIRE_DRAIN", "20"))

mcp = FastMCP("tesla")

# -- Owner API Token Decryption -----------------------------------------------

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

    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT access, refresh FROM tokens LIMIT 1")
            row = cur.fetchone()
            if not row:
                raise RuntimeError("No tokens found in TeslaMate database.")
            encrypted_access = row[0]
            encrypted_refresh = row[1]
    finally:
        if 'conn' in locals():
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


def _get_access_token() -> str:
    """Get a valid Owner API access token from TeslaMate database."""
    tokens = _decrypt_tokens()
    return tokens.get("access", "")


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


# -- DB helper -----------------------------------------------------------------


def _get_conn():
    """Get a Postgres connection to TeslaMate's database."""
    if not HAS_TESLAMATE:
        raise RuntimeError(
            "TeslaMate database not configured. "
            "Set TESLAMATE_DB_HOST and TESLAMATE_DB_PASS environment variables. "
            "See README for setup instructions."
        )
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASS,
        dbname=DB_NAME,
        cursor_factory=psycopg2.extras.RealDictCursor,
        connect_timeout=10,
    )


def _query(sql: str, params: tuple = ()) -> list[dict]:
    """Execute a read-only query and return results as list of dicts."""
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = []
            for row in cur.fetchall():
                rows.append(
                    {
                        k: float(v) if isinstance(v, Decimal) else v
                        for k, v in dict(row).items()
                    }
                )
            return rows
    finally:
        conn.close()


def _query_one(sql: str, params: tuple = ()) -> dict | None:
    """Execute a read-only query and return first result."""
    rows = _query(sql, params)
    return rows[0] if rows else None


def _km_to_mi(km: float | None) -> float | None:
    """Convert km to miles, handling None."""
    return round(km * 0.621371, 1) if km else None


def _c_to_f(c: float | None) -> int | None:
    """Convert Celsius to Fahrenheit, handling None."""
    return round(c * 9 / 5 + 32) if c is not None else None


def _format_distance(km: float) -> str:
    """Format distance based on USE_METRIC_UNITS."""
    if USE_METRIC_UNITS:
        return f"{round(km, 1)} km"
    return f"{_km_to_mi(km)} mi"


def _format_temp(c: float | None) -> str:
    """Format temperature based on USE_METRIC_UNITS."""
    if c is None:
        return "N/A"
    if USE_METRIC_UNITS:
        return f"{round(c)}degC"
    return f"{_c_to_f(c)}degF"


def _format_efficiency(kwh: float, km: float) -> str:
    """Format energy efficiency based on USE_METRIC_UNITS."""
    if km <= 0:
        return "N/A"
    if USE_METRIC_UNITS:
        wh_per_km = kwh * 1000 / km
        return f"{round(wh_per_km, 1)} Wh/km"
    mi = km * 0.621371
    wh_per_mi = kwh * 1000 / mi
    return f"{round(wh_per_mi)} Wh/mi"


def _format_cost(kwh: float) -> str:
    """Format electricity cost based on USE_METRIC_UNITS."""
    if USE_METRIC_UNITS:
        return f"JPY{round(kwh * ELECTRICITY_RATE_RMB, 2)}"
    return f"${round(kwh * ELECTRICITY_RATE, 2)}"


# -- TeslaMate Read Tools ------------------------------------------------------


@mcp.tool()
async def tesla_status() -> str:
    """Current vehicle state -- battery, range, location, climate, odometer.

    Returns the latest position snapshot and vehicle info from TeslaMate.
    """
    car = _query_one(
        f"SELECT id, name, model, efficiency FROM cars WHERE id = {CAR_ID} LIMIT 1"
    )

    pos = _query_one(f"""
        SELECT battery_level, ideal_battery_range_km,
               is_climate_on, inside_temp, outside_temp, driver_temp_setting,
               odometer, speed, power,
               latitude, longitude, date
        FROM positions
        WHERE car_id = {CAR_ID}
        ORDER BY date DESC
        LIMIT 1
    """)

    state = _query_one(f"""
        SELECT state, start_date, end_date
        FROM states
        WHERE car_id = {CAR_ID}
        ORDER BY start_date DESC
        LIMIT 1
    """)

    charge = _query_one(f"""
        SELECT charge_energy_added, duration_min,
               start_battery_level, end_battery_level,
               start_date, end_date
        FROM charging_processes
        WHERE car_id = {CAR_ID}
        ORDER BY start_date DESC
        LIMIT 1
    """)

    # Check geofence for current position
    geofence = None
    if pos and pos.get("latitude") and pos.get("longitude"):
        geofence = _query_one(
            """
            SELECT name, radius, dist.distance_m FROM geofences,
            LATERAL (SELECT (6371000 * acos(
                       cos(radians(%s)) * cos(radians(latitude))
                       * cos(radians(longitude) - radians(%s))
                       + sin(radians(%s)) * sin(radians(latitude))
                   )) AS distance_m) dist
            WHERE dist.distance_m <= radius
            ORDER BY dist.distance_m
            LIMIT 1
        """,
            (pos["latitude"], pos["longitude"], pos["latitude"]),
        )
        if geofence is None:
            geofence = _query_one(
                """
                SELECT name FROM geofences
                WHERE ABS(latitude - %s) < 0.01 AND ABS(longitude - %s) < 0.01
                ORDER BY ABS(latitude - %s) + ABS(longitude - %s)
                LIMIT 1
            """,
                (pos["latitude"], pos["longitude"], pos["latitude"], pos["longitude"]),
            )

    update = _query_one(f"""
        SELECT version FROM updates
        WHERE car_id = {CAR_ID}
        ORDER BY start_date DESC
        LIMIT 1
    """)

    lines = []
    if car:
        name = car.get("name") or car.get("model") or "Tesla"
        model = car.get("model") or ""
        lines.append(f"**{name}** ({model})")

    if update and update.get("version"):
        lines.append(f"Software: {update['version']}")

    if pos:
        bat = pos.get("battery_level")
        range_km = pos.get("ideal_battery_range_km")
        lines.append(f"Battery: {bat}%" + (f" ({_format_distance(range_km)})" if range_km else ""))

        is_charging = (
            charge
            and charge.get("end_date") is None
            and charge.get("start_date") is not None
        )
        if is_charging:
            kwh = charge.get("charge_energy_added") or 0
            lines.append(f"Charging: Yes ({kwh:.1f} kWh added so far)")
        else:
            lines.append("Charging: Not charging")

        if pos.get("is_climate_on"):
            inside_t = _format_temp(pos.get("inside_temp"))
            target_t = _format_temp(pos.get("driver_temp_setting"))
            line = "Climate: ON"
            if inside_t != "N/A":
                line += f", cabin {inside_t}"
            if target_t != "N/A":
                line += f", target {target_t}"
            lines.append(line)
        else:
            inside_t = _format_temp(pos.get("inside_temp"))
            outside_t = _format_temp(pos.get("outside_temp"))
            parts = ["Climate: Off"]
            if inside_t != "N/A":
                parts.append(f"cabin {inside_t}")
            if outside_t != "N/A":
                parts.append(f"outside {outside_t}")
            lines.append(", ".join(parts))

        odo_km = pos.get("odometer")
        if odo_km:
            lines.append(f"Odometer: {_format_distance(odo_km)}")

        if state:
            vehicle_state = state.get("state", "unknown")
            lines.append(f"State: {vehicle_state}")

        if geofence and geofence.get("name"):
            lines.append(f"Location: {geofence['name']}")
        else:
            lat, lon = pos.get("latitude"), pos.get("longitude")
            if lat is not None and lon is not None:
                lines.append(f"Location: {lat:.4f}, {lon:.4f}")
            else:
                lines.append("Location: unknown")

        lines.append(f"Last update: {str(pos.get('date', 'unknown'))[:19]}")

    if charge and charge.get("end_date"):
        kwh = charge.get("charge_energy_added") or 0
        dur = charge.get("duration_min") or 0
        start_bat = charge.get("start_battery_level") or "?"
        end_bat = charge.get("end_battery_level") or "?"
        lines.append(
            f"Last charge: {kwh:.1f} kWh in {dur} min ({start_bat}% -> {end_bat}%)"
        )

    return "\n".join(lines) if lines else "No vehicle data found. Is TeslaMate running?"


@mcp.tool()
async def tesla_charging_history(days: int = 30) -> str:
    """Charging sessions over the last N days.

    Shows energy added, duration, battery range, and location for each session.
    """
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    rows = _query(
        f"""
        SELECT cp.start_date, cp.end_date,
               cp.charge_energy_added, cp.duration_min,
               cp.start_battery_level, cp.end_battery_level,
               a.display_name AS location
        FROM charging_processes cp
        LEFT JOIN positions p ON cp.position_id = p.id
        LEFT JOIN addresses a ON a.id = (
            SELECT a2.id FROM addresses a2
            WHERE ABS(a2.latitude - p.latitude) < 0.001
              AND ABS(a2.longitude - p.longitude) < 0.001
            ORDER BY ABS(a2.latitude - p.latitude) + ABS(a2.longitude - p.longitude)
            LIMIT 1
        )
        WHERE cp.car_id = {CAR_ID} AND cp.start_date >= %s
        ORDER BY cp.start_date DESC
        {_limit_sql(LIMIT_CHARGING)}
    """,
        (cutoff,),
    )

    if not rows:
        return f"No charging sessions in the last {days} days."

    lines = [f"**Charging History** (last {days} days, {len(rows)} sessions)\n"]
    total_kwh = 0.0
    for r in rows:
        kwh = r.get("charge_energy_added") or 0
        total_kwh += kwh
        dur = r.get("duration_min") or 0
        start_pct = r.get("start_battery_level", "?")
        end_pct = r.get("end_battery_level", "?")
        loc = r.get("location") or "Unknown"
        date_str = str(r.get("start_date", ""))[:16]
        lines.append(
            f"- {date_str}: {kwh:.1f} kWh, {dur} min, {start_pct}% -> {end_pct}%, {loc}"
        )

    lines.append(f"\n**Total:** {total_kwh:.1f} kWh across {len(rows)} sessions")
    return "\n".join(lines)


@mcp.tool()
async def tesla_drives(days: int = 30) -> str:
    """Recent drives -- distance, duration, efficiency, start/end locations.

    Shows the last N days of driving activity with energy consumption.
    """
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    rows = _query(
        f"""
        SELECT d.start_date, d.end_date,
               d.distance, d.duration_min,
               d.start_ideal_range_km, d.end_ideal_range_km,
               d.outside_temp_avg,
               sa.display_name AS start_location,
               ea.display_name AS end_location
        FROM drives d
        LEFT JOIN addresses sa ON d.start_address_id = sa.id
        LEFT JOIN addresses ea ON d.end_address_id = ea.id
        WHERE d.car_id = {CAR_ID} AND d.start_date >= %s
        ORDER BY d.start_date DESC
        {_limit_sql(LIMIT_DRIVES)}
    """,
        (cutoff,),
    )

    if not rows:
        return f"No drives recorded in the last {days} days."

    lines = [f"**Drives** (last {days} days, {len(rows)} trips)\n"]
    total_km = 0.0
    total_kwh = 0.0
    total_min = 0
    for r in rows:
        dist_km = r.get("distance") or 0
        total_km += dist_km
        dur = r.get("duration_min") or 0
        total_min += dur
        start = r.get("start_location") or "?"
        end = r.get("end_location") or "?"
        date_str = str(r.get("start_date", ""))[:16]
        range_start = r.get("start_ideal_range_km") or 0
        range_end = r.get("end_ideal_range_km") or 0
        kwh = max(0, (range_start - range_end) * KWH_PER_KM)
        total_kwh += kwh

        eff_str = _format_efficiency(kwh, dist_km) if dist_km > 0 and kwh > 0 else ""

        lines.append(f"- {date_str}: {_format_distance(dist_km)}, {dur} min, {start} -> {end}{eff_str}")

    avg_eff = ""
    if total_km > 0 and total_kwh > 0:
        avg_eff = f", avg {_format_efficiency(total_kwh, total_km)}"
    lines.append(
        f"\n**Total:** {_format_distance(total_km)}, {total_kwh:.1f} kWh, "
        f"{total_min} min across {len(rows)} trips{avg_eff}"
    )
    return "\n".join(lines)


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
    POWER_ACCEL_THRESHOLD = 50   # kW -- above this = aggressive acceleration
    POWER_BRAKE_THRESHOLD = -30  # kW -- below this = harsh braking
    SPEED_THRESHOLD_KMH = 130     # km/h -- above this = speeding

    score = 100
    details = []

    for r in rows:
        power_max = r.get("power_max") or 0
        power_min = r.get("power_min") or 0
        speed_max = r.get("speed_max") or 0

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

    lines = [f"**Driving Score -- {label}**\n"]
    lines.append(f"Score: {score}/100")
    if details:
        lines.append(f"Events: {', '.join(details[:5])}")
    lines.append(f"Drives analyzed: {len(rows)}")
    return "\n".join(lines)


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
        (CAR_ID, limit * 3),
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
        dist_km = r.get("distance") or 0
        dur = r.get("duration_min") or 0
        start = r.get("start_location") or "?"
        end = r.get("end_location") or "?"
        lines.append(f"- {date}: {_format_distance(dist_km)}, {dur} min, {start} -> {end}")
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
        ORDER BY d.start_date DESC
        {_limit_sql(LIMIT_TRIP_CATEGORIES)}
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
    cap_note = f" (last {len(rows)} drives)" if LIMIT_TRIP_CATEGORIES > 0 and len(rows) >= LIMIT_TRIP_CATEGORIES else f" ({len(rows)} drives)"
    lines = [f"**Trip Categories**{cap_note}\n"]
    for cat, cnt in sorted(counts.items(), key=lambda x: -x[1]):
        pct = round(cnt / total * 100) if total > 0 else 0
        lines.append(f"- {cat}: {cnt} ({pct}%)")
    return "\n".join(lines)


@mcp.tool()
async def tesla_battery_health() -> str:
    """Battery degradation trend -- range at 100% charge over time.

    Shows monthly snapshots of ideal range when battery is at 100%.
    """
    rows = _query(f"""
        SELECT date_trunc('month', date) AS month,
               AVG(ideal_battery_range_km) AS avg_ideal_km,
               COUNT(*) AS samples
        FROM positions
        WHERE car_id = {CAR_ID}
          AND battery_level = 100
          AND ideal_battery_range_km IS NOT NULL
        GROUP BY date_trunc('month', date)
        ORDER BY month DESC
        {_limit_sql(LIMIT_BATTERY_HEALTH)}
    """)

    if not rows:
        rows = _query(f"""
            SELECT date, ideal_battery_range_km
            FROM positions
            WHERE car_id = {CAR_ID}
              AND battery_level >= 99
              AND ideal_battery_range_km IS NOT NULL
            ORDER BY date DESC
            {_limit_sql(LIMIT_BATTERY_SAMPLES)}
        """)
        if not rows:
            return "Not enough data for battery health. Need positions at 100% charge."

        lines = ["**Battery Health** (snapshots at ~100% charge)\n"]
        for r in rows:
            range_km = r.get("ideal_battery_range_km")
            date_str = str(r.get("date", ""))[:10]
            lines.append(f"- {date_str}: {_format_distance(range_km)} ideal range at 100%")
        return "\n".join(lines)

    lines = ["**Battery Health** (monthly averages at 100% charge)\n"]
    for r in rows:
        range_km = r.get("avg_ideal_km")
        month = str(r.get("month", ""))[:7]
        samples = r.get("samples", 0)
        lines.append(f"- {month}: {_format_distance(range_km)} ideal range ({samples} samples)")

    if len(rows) >= 2:
        newest = rows[0].get("avg_ideal_km") or 0
        oldest = rows[-1].get("avg_ideal_km") or 0
        if oldest > 0:
            deg_pct = round((1 - newest / oldest) * 100, 1)
            lines.append(f"\n**Degradation:** {deg_pct}% over {len(rows)} months")

    return "\n".join(lines)


@mcp.tool()
async def tesla_efficiency(days: int = 90) -> str:
    """Energy consumption trends -- Wh/mi over time.

    Shows weekly average efficiency from driving data.
    """
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    rows = _query(
        f"""
        SELECT date_trunc('week', start_date) AS week,
               SUM(distance) AS total_km,
               SUM(GREATEST(start_ideal_range_km - end_ideal_range_km, 0)
                   * {KWH_PER_KM}) AS total_kwh,
               SUM(duration_min) AS total_min,
               COUNT(*) AS trips,
               AVG(outside_temp_avg) AS avg_temp
        FROM drives
        WHERE car_id = {CAR_ID} AND start_date >= %s AND distance > 0
        GROUP BY date_trunc('week', start_date)
        ORDER BY week DESC
    """,
        (cutoff,),
    )

    if not rows:
        return f"No driving data in the last {days} days."

    lines = [f"**Efficiency** (last {days} days, weekly)\n"]
    for r in rows:
        km = r.get("total_km") or 0
        kwh = r.get("total_kwh") or 0
        trips = r.get("trips", 0)
        week = str(r.get("week", ""))[:10]
        temp = r.get("avg_temp")
        temp_str = f", avg {_format_temp(temp)}" if temp is not None else ""

        eff_str = _format_efficiency(kwh, km) if km > 0 and kwh > 0 else ""

        lines.append(
            f"- {week}: {_format_distance(km)}, {kwh:.1f} kWh, {trips} trips{eff_str}{temp_str}"
        )

    return "\n".join(lines)


@mcp.tool()
async def tesla_location_history(days: int = 7) -> str:
    """Where the car has been -- top locations by time spent.

    Groups positions by proximity and shows time at each cluster.
    """
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()

    rows = _query(
        f"""
        SELECT ROUND(latitude::numeric, 3) AS lat,
               ROUND(longitude::numeric, 3) AS lon,
               COUNT(*) AS position_count,
               MIN(date) AS first_seen,
               MAX(date) AS last_seen
        FROM positions
        WHERE car_id = {CAR_ID} AND date >= %s
        GROUP BY ROUND(latitude::numeric, 3), ROUND(longitude::numeric, 3)
        ORDER BY position_count DESC
        {_limit_sql(LIMIT_LOCATION_HISTORY)}
    """,
        (cutoff,),
    )

    if not rows:
        return f"No location data in the last {days} days."

    geofences = _query("SELECT name, latitude, longitude, radius FROM geofences")

    lines = [f"**Location History** (last {days} days)\n"]
    for r in rows:
        lat = float(r.get("lat", 0))
        lon = float(r.get("lon", 0))
        count = r.get("position_count", 0)
        last = str(r.get("last_seen", ""))[:16]

        loc = f"{lat}, {lon}"
        for gf in geofences:
            dlat = abs(gf["latitude"] - lat)
            dlon = abs(gf["longitude"] - lon)
            if dlat < 0.005 and dlon < 0.005:
                loc = gf["name"]
                break

        lines.append(f"- {loc}: {count} data points, last seen {last}")

    return "\n".join(lines)


@mcp.tool()
async def tesla_state_history(days: int = 7) -> str:
    """Vehicle state transitions -- online, asleep, offline.

    Shows when the car was awake vs sleeping, useful for vampire drain analysis.
    """
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    rows = _query(
        f"""
        SELECT state, start_date, end_date
        FROM states
        WHERE car_id = {CAR_ID} AND start_date >= %s
        ORDER BY start_date DESC
        {_limit_sql(LIMIT_STATE_HISTORY)}
    """,
        (cutoff,),
    )

    if not rows:
        return f"No state data in the last {days} days."

    lines = [f"**State History** (last {days} days, {len(rows)} transitions)\n"]

    totals: dict[str, float] = {}
    for r in rows:
        st = r.get("state", "unknown")
        start = r.get("start_date")
        end = r.get("end_date") or datetime.utcnow()
        if start:
            dur_h = (end - start).total_seconds() / 3600
            totals[st] = totals.get(st, 0) + dur_h

    for st, hours in sorted(totals.items(), key=lambda x: -x[1]):
        lines.append(f"- {st}: {hours:.1f} hours")

    lines.append("\nRecent transitions:")
    for r in rows[:20]:
        st = r.get("state", "?")
        start = str(r.get("start_date", ""))[:16]
        end = r.get("end_date")
        dur = ""
        if end and r.get("start_date"):
            dur_min = round((end - r["start_date"]).total_seconds() / 60)
            dur = f" ({dur_min} min)"
        lines.append(f"- {start}: {st}{dur}")

    return "\n".join(lines)


@mcp.tool()
async def tesla_software_updates() -> str:
    """Firmware version history -- all recorded software versions and install dates."""
    rows = _query(f"""
        SELECT version, start_date, end_date
        FROM updates
        WHERE car_id = {CAR_ID}
        ORDER BY start_date DESC
        {_limit_sql(LIMIT_SOFTWARE_UPDATES)}
    """)

    if not rows:
        return "No software update history found."

    lines = ["**Software Updates**\n"]
    for r in rows:
        ver = r.get("version", "unknown")
        start = str(r.get("start_date", ""))[:16]
        end = r.get("end_date")
        dur = ""
        if end and r.get("start_date"):
            dur_min = round((end - r["start_date"]).total_seconds() / 60)
            dur = f" ({dur_min} min)"
        lines.append(f"- {start}: {ver}{dur}")

    return "\n".join(lines)


# -- Owner API Live Data -------------------------------------------------------


@mcp.tool()
async def tesla_live() -> str:
    """Live vehicle data from Tesla Owner API -- real-time battery, charging, climate.

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

    # Find the first vehicle (or filter by CAR_ID - for multi-car support later)
    vehicle = vehicles[0]
    vehicle_id = vehicle.get("id")
    if not vehicle_id:
        return "Could not determine vehicle ID from API response."

    # Get live vehicle data
    data = await _owner_api_get(f"/api/1/vehicles/{vehicle_id}/vehicle_data")
    r = data.get("response", {})
    cs = r.get("charge_state", {})
    cl = r.get("climate_state", {})
    vs = r.get("vehicle_state", {})
    ds = r.get("drive_state", {})

    vehicle_name = vs.get("vehicle_name") or "Tesla"
    lines = [f"**{vehicle_name}** (live)\n"]

    # Battery range - API returns miles
    bat_range = cs.get('battery_range', 0)
    if USE_METRIC_UNITS:
        bat_range_km = round(bat_range * 1.60934)
        lines.append(f"Battery: {cs.get('battery_level')}% ({bat_range_km} km)")
    else:
        lines.append(f"Battery: {cs.get('battery_level')}% ({bat_range:.0f} mi)")

    lines.append(
        f"Charging: {cs.get('charging_state')} (limit {cs.get('charge_limit_soc')}%)"
    )
    if cs.get("charging_state") == "Charging":
        rate = cs.get("charge_rate", 0)
        added = cs.get("charge_energy_added", 0)
        mins = cs.get("minutes_to_full_charge", 0)
        if USE_METRIC_UNITS:
            rate_kmh = round(rate * 1.60934)
            lines.append(f"  Rate: {rate_kmh} km/h, {added:.1f} kWh added, {mins} min to full")
        else:
            lines.append(f"  Rate: {rate} mph, {added:.1f} kWh added, {mins} min to full")

    inside_t = _format_temp(cl.get("inside_temp"))
    outside_t = _format_temp(cl.get("outside_temp"))
    lines.append(
        f"Climate: {'ON' if cl.get('is_climate_on') else 'Off'}"
        f", inside {inside_t}, outside {outside_t}"
    )
    if cl.get("is_climate_on"):
        target_t = _format_temp(cl.get("driver_temp_setting"))
        lines.append(f"  Target: {target_t}")

    lines.append(f"Locked: {'Yes' if vs.get('locked') else 'No'}")
    lines.append(f"Sentry: {'On' if vs.get('sentry_mode') else 'Off'}")
    lines.append(f"Software: {vs.get('car_version', '?')}")

    # Odometer - API returns miles
    odo = vs.get('odometer', 0)
    if USE_METRIC_UNITS:
        odo_km = round(odo * 1.60934)
        lines.append(f"Odometer: {odo_km:,} km")
    else:
        lines.append(f"Odometer: {odo:,.0f} mi")

    if ds.get("speed"):
        speed = ds['speed']
        if USE_METRIC_UNITS:
            speed_kmh = round(speed * 1.60934)
            lines.append(f"Driving: {speed_kmh} km/h")
        else:
            lines.append(f"Driving: {speed} mph")
    else:
        lines.append("Driving: Parked")

    # Vehicle location
    lat = ds.get("latitude")
    lon = ds.get("longitude")
    if lat and lon:
        lines.append(f"Location: {lat:.5f}, {lon:.5f}")
        # Try to match with TeslaMate geofences
        try:
            nearby = _query_one(
                f"""
                SELECT name, latitude, longitude, radius,
                       6371 * 2 * ASIN(SQRT(
                           POWER(SIN((RADIANS(%s) - RADIANS(latitude)) / 2), 2) +
                           COS(RADIANS(%s)) * COS(RADIANS(latitude)) *
                           POWER(SIN((RADIANS(%s) - RADIANS(longitude)) / 2), 2)
                       )) AS distance_km
                FROM geofences
                ORDER BY distance_km ASC LIMIT 1
                """,
                (lat, lat, lon),
            )
            if nearby and nearby.get("name"):
                dist = nearby.get("distance_km", 0)
                dist_str = f" ({dist:.1f}km away)" if dist and dist > 0.5 else ""
                lines.append(f"  Near: {nearby['name']}{dist_str}")
        except Exception:
            pass  # Geofence lookup is best-effort
    else:
        lines.append("Location: unavailable")

    tires = []
    for pos, label in [("fl", "FL"), ("fr", "FR"), ("rl", "RL"), ("rr", "RR")]:
        bar = vs.get(f"tpms_pressure_{pos}")
        if bar:
            warn = " !" if vs.get(f"tpms_soft_warning_{pos}") else ""
            if USE_METRIC_UNITS:
                tires.append(f"{label}:{bar:.2f} bar{warn}")
            else:
                psi = round(bar * 14.5038, 1)
                tires.append(f"{label}:{psi} psi{warn}")
    if tires:
        lines.append(f"Tires: {', '.join(tires)}")

    media = vs.get("media_info", {})
    title = media.get("now_playing_title", "")
    artist = media.get("now_playing_artist", "")
    if title:
        playing = title
        if artist:
            playing = f"{artist} -- {title}"
        lines.append(f"Playing: {playing} ({media.get('now_playing_source', '?')})")

    update = vs.get("software_update", {})
    if update.get("status") and update.get("version", "").strip():
        lines.append(
            f"Update available: {update['version'].strip()} "
            f"(est. {update.get('expected_duration_sec', 0) // 60} min)"
        )

    return "\n".join(lines)


# -- Analytics Tools -----------------------------------------------------------


@mcp.tool()
async def tesla_savings(
    gas_price: float = None,
    mpg_equivalent: int = None,
) -> str:
    """Gas savings scorecard -- how much you've saved vs a gas car.

    Args:
        gas_price: Gas price per gallon (default from TESLA_GAS_PRICE env, or $3.50)
        mpg_equivalent: Comparable gas vehicle MPG (default from TESLA_GAS_MPG env, or 28)
    """
    _gas = gas_price or GAS_PRICE
    _mpg = mpg_equivalent or GAS_MPG

    lifetime = _query_one(f"""
        SELECT COALESCE(SUM(distance), 0) AS total_km,
               COALESCE(SUM(GREATEST(start_ideal_range_km - end_ideal_range_km, 0)
                   * {KWH_PER_KM}), 0) AS total_kwh
        FROM drives WHERE car_id = {CAR_ID} AND distance > 0
    """)
    monthly = _query_one(f"""
        SELECT COALESCE(SUM(distance), 0) AS total_km,
               COALESCE(SUM(GREATEST(start_ideal_range_km - end_ideal_range_km, 0)
                   * {KWH_PER_KM}), 0) AS total_kwh
        FROM drives WHERE car_id = {CAR_ID} AND distance > 0
          AND date_trunc('month', start_date) = date_trunc('month', NOW())
    """)

    if not lifetime:
        return "No driving data yet."

    lines = ["**Gas Savings Scorecard**\n"]

    for label, data in [("This Month", monthly), ("Lifetime", lifetime)]:
        if not data or not data.get("total_km"):
            continue
        km = data["total_km"]
        kwh = data["total_kwh"] or 0

        if USE_METRIC_UNITS:
            elec_cost = round(kwh * ELECTRICITY_RATE_RMB, 2)
            lines.append(f"**{label}:** {km:,.1f} km")
            lines.append(f"  Electricity: {kwh:,.1f} kWh x JPY{ELECTRICITY_RATE_RMB} = JPY{elec_cost:,.2f}")
            lines.append("")
        else:
            mi = round(km * 0.621371, 1)
            elec_cost = round(kwh * ELECTRICITY_RATE, 2)
            gas_cost = round(mi / _mpg * _gas, 2)
            saved = round(gas_cost - elec_cost, 2)
            cost_per_mi = round(elec_cost / mi * 100, 1) if mi > 0 else 0

            lines.append(f"**{label}:** {mi:,.1f} mi")
            lines.append(
                f"  Electricity: {kwh:,.1f} kWh x ${ELECTRICITY_RATE} = ${elec_cost:,.2f}"
            )
            lines.append(
                f"  Gas equivalent: {mi:,.1f} mi / {_mpg} MPG x "
                f"${_gas}/gal = ${gas_cost:,.2f}"
            )
            lines.append(
                f"  **Saved: ${saved:,.2f}** ({cost_per_mi}c/mi electric vs "
                f"{round(_gas / _mpg * 100, 1)}c/mi gas)"
            )
            lines.append("")

    return "\n".join(lines)


@mcp.tool()
async def tesla_trip_cost(
    destination: str,
    gas_price: float = None,
    mpg_equivalent: int = None,
) -> str:
    """Estimate trip cost to a destination -- kWh, cost, range check.

    Uses your personal 30-day average efficiency and current battery level.

    Args:
        destination: City, address, or place name (e.g. "Atlanta, GA")
        gas_price: Gas price per gallon (default from TESLA_GAS_PRICE env)
        mpg_equivalent: Comparable gas vehicle MPG (default from TESLA_GAS_MPG env)
    """
    _gas = gas_price or GAS_PRICE
    _mpg = mpg_equivalent or GAS_MPG

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": destination, "format": "json", "limit": "1"},
            headers={"User-Agent": "TeslaMCP/1.0"},
        )
        results = resp.json()
    if not results:
        return f"Could not geocode '{destination}'."

    dest_lat = float(results[0]["lat"])
    dest_lon = float(results[0]["lon"])
    dest_name = results[0].get("display_name", destination).split(",")[0]

    pos = _query_one(f"""
        SELECT latitude, longitude, battery_level, ideal_battery_range_km
        FROM positions WHERE car_id = {CAR_ID}
        ORDER BY date DESC LIMIT 1
    """)
    if not pos:
        return "No current position data."

    lat1, lon1 = math.radians(pos["latitude"]), math.radians(pos["longitude"])
    lat2, lon2 = math.radians(dest_lat), math.radians(dest_lon)
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    )
    straight_mi = 3959 * 2 * math.asin(math.sqrt(a))
    road_mi = round(straight_mi * 1.3, 1)
    round_trip = round(road_mi * 2, 1)

    eff = _query_one(f"""
        SELECT COALESCE(SUM(GREATEST(start_ideal_range_km - end_ideal_range_km, 0)
                   * {KWH_PER_KM}), 0) AS kwh,
               COALESCE(SUM(distance), 0) AS km
        FROM drives WHERE car_id = {CAR_ID}
          AND start_date >= NOW() - INTERVAL '30 days' AND distance > 0
    """)

    if USE_METRIC_UNITS:
        wh_per_km = 180  # default Wh/km
        if eff and eff["km"] > 0:
            wh_per_km = round(eff["kwh"] * 1000 / eff["km"])
        road_km = round(straight_mi * 1.60934 * 1.3, 1)
        round_trip_km = round(road_km * 2, 1)
        kwh_round = round(round_trip_km * wh_per_km / 1000, 1)
        cost_round = round(kwh_round * ELECTRICITY_RATE_RMB, 2)

        bat = pos.get("battery_level", 0)
        range_km = round(pos.get("ideal_battery_range_km") or 0)

        lines = [
            f"**Trip to {dest_name}** ({road_km} km each way, {round_trip_km} km round trip)\n"
        ]
        lines.append(f"Estimated: {kwh_round} kWh @ {wh_per_km} Wh/km (your 30-day avg)")
        lines.append(f"Cost: JPY{cost_round}")
        lines.append(f"Current battery: {bat}% ({_format_distance(range_km)})")

        if range_km >= round_trip_km:
            lines.append("Range: Sufficient for round trip")
        elif range_km >= road_km:
            lines.append("Range: Sufficient one-way, charge at destination for return")
        else:
            pct_needed = min(95, round(round_trip_km / range_km * bat)) if range_km > 0 else 95
            lines.append(
                f"Range: NOT sufficient -- charge to {pct_needed}%+ before departure"
            )
    else:
        wh_per_mi = 300  # default
        if eff and eff["km"] > 0:
            wh_per_mi = round(eff["kwh"] * 1000 / (eff["km"] * 0.621371))

        kwh_round = round(round_trip * wh_per_mi / 1000, 1)
        cost_round = round(kwh_round * ELECTRICITY_RATE, 2)
        gas_equiv = round(round_trip / _mpg * _gas, 2)

        bat = pos.get("battery_level", 0)
        range_mi = round((pos.get("ideal_battery_range_km") or 0) * 0.621371)

        lines = [
            f"**Trip to {dest_name}** ({road_mi} mi each way, {round_trip} mi round trip)\n"
        ]
        lines.append(f"Estimated: {kwh_round} kWh @ {wh_per_mi} Wh/mi (your 30-day avg)")
        lines.append(f"Cost: ${cost_round} (gas equivalent: ${gas_equiv})")
        lines.append(f"Current battery: {bat}% ({range_mi} mi)")

        if range_mi >= round_trip:
            lines.append("Range: Sufficient for round trip")
        elif range_mi >= road_mi:
            lines.append("Range: Sufficient one-way, charge at destination for return")
        else:
            pct_needed = min(95, round(round_trip / range_mi * bat)) if range_mi > 0 else 95
            lines.append(
                f"Range: NOT sufficient -- charge to {pct_needed}%+ before departure"
            )

    return "\n".join(lines)


@mcp.tool()
async def tesla_efficiency_by_temp() -> str:
    """Efficiency curve by temperature -- Wh/mi at different temps.

    Shows how outside temperature affects energy consumption.
    """
    rows = _query(f"""
        SELECT
            CASE
                WHEN outside_temp_avg < 0 THEN 'Below 32degF'
                WHEN outside_temp_avg < 4.4 THEN '32-40degF'
                WHEN outside_temp_avg < 10 THEN '40-50degF'
                WHEN outside_temp_avg < 15.6 THEN '50-60degF'
                WHEN outside_temp_avg < 21.1 THEN '60-70degF'
                WHEN outside_temp_avg < 26.7 THEN '70-80degF'
                WHEN outside_temp_avg < 32.2 THEN '80-90degF'
                ELSE 'Above 90degF'
            END AS temp_range,
            COUNT(*) AS trips,
            SUM(distance) AS total_km,
            SUM(GREATEST(start_ideal_range_km - end_ideal_range_km, 0)
                * {KWH_PER_KM}) AS total_kwh
        FROM drives
        WHERE car_id = {CAR_ID} AND distance > 1
          AND (start_ideal_range_km - end_ideal_range_km) > 0
          AND outside_temp_avg IS NOT NULL
        GROUP BY temp_range
        ORDER BY MIN(outside_temp_avg)
    """)

    if not rows:
        return "Not enough driving data with temperature readings."

    if USE_METRIC_UNITS:
        # Temperature bins in Celsius
        temp_bins = {
            'Below 32degF': 'Below 0degC',
            '32-40degF': '0-4degC',
            '40-50degF': '4-10degC',
            '50-60degF': '10-16degC',
            '60-70degF': '16-21degC',
            '70-80degF': '21-27degC',
            '80-90degF': '27-32degC',
            'Above 90degF': 'Above 32degC',
        }
        lines = ["**Efficiency by Temperature**\n"]
        lines.append(f"{'Temp Range':<15} {'Trips':>6} {'Wh/km':>8} {'km':>10}")
        lines.append("-" * 45)
        for r in rows:
            km = r.get("total_km") or 0
            kwh = r.get("total_kwh") or 0
            wh_per_km = round(kwh * 1000 / km) if km > 0 else 0
            temp_range = temp_bins.get(r['temp_range'], r['temp_range'])
            lines.append(
                f"{temp_range:<15} {r['trips']:>6} {wh_per_km:>7} {round(km):>9,}"
            )
    else:
        lines = ["**Efficiency by Temperature**\n"]
        lines.append(f"{'Temp Range':<15} {'Trips':>6} {'Wh/mi':>8} {'Miles':>10}")
        lines.append("-" * 45)
        for r in rows:
            km = r.get("total_km") or 0
            kwh = r.get("total_kwh") or 0
            mi = km * 0.621371
            wh_mi = round(kwh * 1000 / mi) if mi > 0 else 0
            lines.append(
                f"{r['temp_range']:<15} {r['trips']:>6} {wh_mi:>7} {round(mi):>9,}"
            )

    return "\n".join(lines)


@mcp.tool()
async def tesla_charging_by_location() -> str:
    """Charging patterns by location -- where you charge and how much."""
    rows = _query(f"""
        SELECT a.display_name AS location,
               COUNT(*) AS sessions,
               COALESCE(SUM(cp.charge_energy_added), 0) AS total_kwh,
               COALESCE(AVG(cp.charge_energy_added), 0) AS avg_kwh,
               COALESCE(SUM(cp.duration_min), 0) AS total_min
        FROM charging_processes cp
        JOIN positions p ON cp.position_id = p.id
        LEFT JOIN addresses a ON a.id = (
            SELECT a2.id FROM addresses a2
            WHERE ABS(a2.latitude - p.latitude) < 0.005
              AND ABS(a2.longitude - p.longitude) < 0.005
            LIMIT 1
        )
        WHERE cp.car_id = {CAR_ID} AND cp.end_date IS NOT NULL
        GROUP BY a.display_name
        ORDER BY total_kwh DESC
        {_limit_sql(LIMIT_CHARGING_BY_LOC)}
    """)

    if not rows:
        return "No charging data yet."

    lines = ["**Charging by Location**\n"]
    for r in rows:
        loc = r.get("location") or "Unknown"
        sessions = r.get("sessions", 0)
        kwh = r.get("total_kwh", 0)
        cost_str = _format_cost(kwh)
        lines.append(f"- **{loc}**: {sessions} sessions, {kwh:.1f} kWh (~{cost_str})")

    return "\n".join(lines)


@mcp.tool()
async def tesla_top_destinations(limit: int = 15) -> str:
    """Most visited locations ranked by number of visits.

    Args:
        limit: Number of destinations to show (default: 15)
    """
    rows = _query(
        f"""
        SELECT ea.display_name AS destination,
               COUNT(*) AS visits,
               COALESCE(SUM(d.distance), 0) AS total_km
        FROM drives d
        JOIN addresses ea ON d.end_address_id = ea.id
        WHERE d.car_id = {CAR_ID} AND d.distance > 1
        GROUP BY ea.display_name
        ORDER BY visits DESC
        LIMIT %s
    """,
        (limit,),
    )

    if not rows:
        return "No driving data yet."

    lines = ["**Top Destinations**\n"]
    for i, r in enumerate(rows, 1):
        dest = r.get("destination") or "Unknown"
        visits = r.get("visits", 0)
        km = r.get("total_km") or 0
        lines.append(f"{i}. {dest} -- {visits} visits ({_format_distance(km)} total)")

    return "\n".join(lines)


@mcp.tool()
async def tesla_longest_trips(limit: int = 10) -> str:
    """Top drives ranked by distance -- your epic road trips.

    Args:
        limit: Number of trips to show (default: 10)
    """
    rows = _query(
        f"""
        SELECT d.start_date, d.distance, d.duration_min,
               GREATEST(d.start_ideal_range_km - d.end_ideal_range_km, 0)
                   * {KWH_PER_KM} AS consumption_kwh,
               sa.display_name AS start_loc,
               ea.display_name AS end_loc
        FROM drives d
        LEFT JOIN addresses sa ON d.start_address_id = sa.id
        LEFT JOIN addresses ea ON d.end_address_id = ea.id
        WHERE d.car_id = {CAR_ID} AND d.distance > 0
        ORDER BY d.distance DESC
        LIMIT %s
    """,
        (limit,),
    )

    if not rows:
        return "No driving data yet."

    lines = ["**Longest Trips**\n"]
    for i, r in enumerate(rows, 1):
        dist_km = r.get("distance") or 0
        dur = r.get("duration_min") or 0
        start = r.get("start_loc") or "?"
        end = r.get("end_loc") or "?"
        date = str(r.get("start_date", ""))[:10]
        kwh = r.get("consumption_kwh") or 0
        lines.append(f"{i}. {_format_distance(dist_km)} -- {start} -> {end} ({date}, {dur}min, {kwh:.1f}kWh)")

    return "\n".join(lines)


@mcp.tool()
async def tesla_monthly_report(year: int, month: int) -> str:
    """Monthly driving report with stats and comparison to previous month.

    Args:
        year: Year (e.g., 2026)
        month: Month (1-12)
    """
    start = datetime(year, month, 1)
    if month == 12:
        next_start = datetime(year + 1, 1, 1)
    else:
        next_start = datetime(year, month + 1, 1)
    if month == 1:
        prev_start = datetime(year - 1, 12, 1)
    else:
        prev_start = datetime(year, month - 1, 1)

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

    if USE_METRIC_UNITS:
        lines = [f"**Monthly Report -- {year}-{month:02d}**\n"]
        lines.append(f"Trips: {trips}")
        lines.append(f"Distance: {km:.1f} km")
        lines.append(f"Energy: {kwh:.1f} kWh")
        lines.append(f"Avg efficiency: {_format_efficiency(kwh, km)}")
        lines.append(f"Est. cost: {_format_cost(kwh)}")
        lines.append(f"Time driving: {minutes} min")
    else:
        mi = round(km * 0.621371)
        wh_mi = round(kwh * 1000 / (km * 0.621371)) if km > 0 else 0
        cost = round(kwh * ELECTRICITY_RATE, 2)
        lines = [f"**Monthly Report -- {year}-{month:02d}**\n"]
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
    if not vehicle_id:
        return "Could not determine vehicle ID from API response."

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
        if USE_METRIC_UNITS:
            display = f"{bar:.2f} bar"
        else:
            display = f"{psi} psi"
        status = "OK"
        if bar < TPMS_MIN:
            status = f"LOW (< {TPMS_MIN} bar)"
        elif bar > TPMS_MAX:
            status = f"HIGH (> {TPMS_MAX} bar)"
        soft = vs.get(f"tpms_soft_warning_{pos}")
        if soft:
            status = status + " + SOFT WARNING"
        pressures[pos] = bar
        lines.append(f"{label}: {display} -- {status}")

    # Check consistency
    if len(pressures) >= 3:
        vals = list(pressures.values())
        avg = sum(vals) / len(vals)
        for pos, bar in pressures.items():
            if abs(bar - avg) > TPMS_WARN_DELTA:
                label = dict(positions).get(pos, pos)
                if USE_METRIC_UNITS:
                    lines.append(f"  ! {label} deviates {abs(bar-avg):.2f} bar from average")
                else:
                    lines.append(f"  ! {label} deviates {abs(bar-avg)*14.5038:.1f} psi from average")
        if USE_METRIC_UNITS:
            lines.append(f"Average: {round(avg,2)} bar")
        else:
            lines.append(f"Average: {round(avg*14.5038,1)} psi")

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
        {_limit_sql(LIMIT_TPMS_HISTORY)}
        """,
        (CAR_ID, cutoff),
    )

    if not rows:
        return f"No TPMS data in the last {days} days."

    unit_label = "bar" if USE_METRIC_UNITS else "psi"
    lines = [f"**TPMS History** (last {days} days, {len(rows)} records)\n"]
    for r in rows:
        date = str(r.get("date", ""))[:16]
        fl = r.get("tpms_pressure_fl")
        fr = r.get("tpms_pressure_fr")
        rl = r.get("tpms_pressure_rl")
        rr = r.get("tpms_pressure_rr")
        if USE_METRIC_UNITS:
            fl_s = f"{fl:.2f}" if fl else "--"
            fr_s = f"{fr:.2f}" if fr else "--"
            rl_s = f"{rl:.2f}" if rl else "--"
            rr_s = f"{rr:.2f}" if rr else "--"
        else:
            fl_s = f"{round(fl*14.5038,1)}" if fl else "--"
            fr_s = f"{round(fr*14.5038,1)}" if fr else "--"
            rl_s = f"{round(rl*14.5038,1)}" if rl else "--"
            rr_s = f"{round(rr*14.5038,1)}" if rr else "--"
        lines.append(f"{date}: FL={fl_s} FR={fr_s} RL={rl_s} RR={rr_s} {unit_label}")
    return "\n".join(lines)


@mcp.tool()
async def tesla_monthly_summary(months: int = 6) -> str:
    """Monthly driving summary -- miles, kWh, cost, efficiency.

    Args:
        months: Number of months to show (default: 6)
    """
    rows = _query(
        f"""
        SELECT date_trunc('month', start_date) AS month,
               COUNT(*) AS trips,
               COALESCE(SUM(distance), 0) AS total_km,
               COALESCE(SUM(GREATEST(start_ideal_range_km - end_ideal_range_km, 0)
                   * {KWH_PER_KM}), 0) AS total_kwh,
               COALESCE(SUM(duration_min), 0) AS total_min
        FROM drives
        WHERE car_id = {CAR_ID} AND distance > 0
        GROUP BY date_trunc('month', start_date)
        ORDER BY month DESC
        LIMIT %s
    """,
        (months,),
    )

    if not rows:
        return "No driving data yet."

    if USE_METRIC_UNITS:
        lines = ["**Monthly Summary**\n"]
        lines.append(
            f"{'Month':<12} {'Trips':>6} {'km':>10} {'kWh':>8} {'Wh/km':>7} {'Cost':>8}"
        )
        lines.append("-" * 57)

        for r in rows:
            month = str(r.get("month", ""))[:7]
            trips = r.get("trips", 0)
            km = r.get("total_km") or 0
            kwh = r.get("total_kwh") or 0
            eff_str = _format_efficiency(kwh, km) if km > 0 else "N/A"
            cost_str = _format_cost(kwh)
            lines.append(
                f"{month:<12} {trips:>6} {km:>9,} {kwh:>7.1f} {eff_str:>7} {cost_str:>8}"
            )
    else:
        lines = ["**Monthly Summary**\n"]
        lines.append(
            f"{'Month':<12} {'Trips':>6} {'Miles':>10} {'kWh':>8} {'Wh/mi':>7} {'Cost':>8}"
        )
        lines.append("-" * 57)

        for r in rows:
            month = str(r.get("month", ""))[:7]
            trips = r.get("trips", 0)
            km = r.get("total_km") or 0
            mi = round(km * 0.621371)
            kwh = r.get("total_kwh") or 0
            wh_mi = round(kwh * 1000 / (km * 0.621371)) if km > 0 else 0
            cost = round(kwh * ELECTRICITY_RATE, 2)
            lines.append(
                f"{month:<12} {trips:>6} {mi:>9,} {kwh:>7.1f} {wh_mi:>7} ${cost:>6.2f}"
            )

    return "\n".join(lines)


@mcp.tool()
async def tesla_vampire_drain(days: int = 14) -> str:
    """Vampire drain analysis -- battery loss while parked overnight.

    Checks for periods where the car was parked (no drives) for 8+ hours
    and measures battery drop.

    Args:
        days: Number of days to analyze (default: 14)
    """
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    rows = _query(
        f"""
        WITH ordered AS (
            SELECT date, battery_level,
                   LAG(battery_level) OVER (ORDER BY date) AS prev_level,
                   LAG(date) OVER (ORDER BY date) AS prev_date
            FROM positions
            WHERE car_id = {CAR_ID} AND date >= %s AND battery_level IS NOT NULL
            ORDER BY date
        )
        SELECT date, prev_date, battery_level, prev_level,
               prev_level - battery_level AS drain,
               EXTRACT(EPOCH FROM (date - prev_date)) / 3600 AS hours_parked
        FROM ordered
        WHERE prev_level IS NOT NULL
          AND prev_level - battery_level > 0
          AND EXTRACT(EPOCH FROM (date - prev_date)) / 3600 >= 8
          AND EXTRACT(EPOCH FROM (date - prev_date)) / 3600 <= 48
        ORDER BY drain DESC
        {_limit_sql(LIMIT_VAMPIRE_DRAIN)}
    """,
        (cutoff,),
    )

    if not rows:
        return f"No significant vampire drain detected in the last {days} days."

    lines = [f"**Vampire Drain** (last {days} days)\n"]
    total_drain = 0
    for r in rows:
        drain = r.get("drain", 0)
        total_drain += drain
        hours = r.get("hours_parked", 0)
        rate = round(drain / hours, 2) if hours > 0 else 0
        date = str(r.get("prev_date", ""))[:10]
        lines.append(f"- {date}: -{drain}% over {hours:.0f}h ({rate}%/hr)")

    avg_rate = round(
        total_drain
        / len(rows)
        / (sum(r.get("hours_parked", 8) for r in rows) / len(rows)),
        2,
    )
    lines.append(f"\nAverage drain rate: {avg_rate}%/hr")
    if avg_rate > 1.0:
        lines.append(
            "! Above normal -- check sentry mode camera activity "
            "or third-party app polling"
        )
    elif avg_rate > 0.5:
        lines.append("Slightly elevated -- sentry mode active?")
    else:
        lines.append("Normal range for a parked Tesla")

    return "\n".join(lines)


# -- Entry point ---------------------------------------------------------------

if __name__ == "__main__":
    if MCP_TRANSPORT == "streamable-http":
        mcp.run(transport="streamable-http", host=HTTP_HOST, port=HTTP_PORT)
    else:
        mcp.run()
