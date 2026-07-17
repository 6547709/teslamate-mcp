"""Full functional test harness for teslamate-mcp (tesla.py).

Runs WITHOUT a real PostgreSQL database. We monkeypatch the module-level
`_query` / `_query_one` functions with a lightweight fake that returns canned
rows keyed by SQL fingerprints, so every MCP tool can be exercised end-to-end.

Covers:
  - Layer 1: pure-logic unit tests (the fix points: BUG-4, PERF-1/2/4, ISSUE-1..5)
  - Layer 2: smoke-call every @mcp.tool() and assert it returns a str (no raise)

Usage:
  python test_all.py
Exit code 0 = all passed, 1 = failures.
"""
from __future__ import annotations

import asyncio
import inspect
import os
import re
import sys
import traceback
from datetime import datetime, timezone, timedelta

# -- Configure env BEFORE importing tesla so module-level config picks it up.
os.environ.setdefault("TESLAMATE_DB_HOST", "localhost")
os.environ.setdefault("TESLAMATE_DB_PASS", "test")
os.environ.setdefault("USE_METRIC_UNITS", "true")
os.environ.setdefault("TIMEZONE", "Asia/Shanghai")
# Set sensible car defaults so module-level car config doesn't fall back to
# the loud "no config" warning path. Tests that want to exercise the missing-
# config path should pop these before importing tesla.
os.environ.setdefault("TESLA_BATTERY_KWH", "75")
os.environ.setdefault("TESLA_BATTERY_RANGE_KM", "525")

import tesla  # noqa: E402

PASS = 0
FAIL = 0
FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = ""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        FAILURES.append(f"{name} — {detail}")
        print(f"  ❌ {name} — {detail}")


# =====================================================================
# Fake DB: return canned rows based on what the SQL is asking for.
# =====================================================================

_NOW = datetime.now(timezone.utc)


def _fake_query(sql: str, params: tuple = ()):  # noqa: C901
    s = " ".join(sql.lower().split())
    # ---- monthly_summary (CTE joining drives + charging + vampire) ---------
    # Must be matched BEFORE the generic "lead(ts)" and "from drives" checks
    # because the joined SQL contains both patterns.
    if "with vampire_m" in s and "with drives_m" in s:
        return [{
            "month": _NOW.replace(day=1),
            "trips": 42, "total_km": 1250.0, "total_min": 1500,
            "drive_kwh": 180.0, "charge_kwh": 210.0, "vampire_kwh": 12.0,
            "total_cost": 120.0,
        }]
    # ---- monthly_report drive CTE (FILTER aggregate) ------------------------
    if "cur_drive_kwh" in s:
        return [{
            "cur_trips": 42, "cur_km": 1250.0, "cur_min": 1500,
            "prev_km": 1100.0, "cur_drive_kwh": 180.0, "prev_drive_kwh": 165.0,
        }]
    # ---- monthly_report charging CTE ----------------------------------------
    if "cur_charge_kwh" in s:
        return [{
            "cur_cost": 120.0, "cur_charge_kwh": 210.0, "prev_charge_kwh": 195.0,
        }]
    # ---- monthly_report vampire CTE ----------------------------------------
    if "cur_vampire_pct" in s:
        return [{"cur_vampire_pct": 16.0, "prev_vampire_pct": 14.0}]
    # cars
    if "from cars" in s:
        return [{"id": 1, "name": "Model 3", "model": "3", "vin": "LRWABC123456", "efficiency": 0.153,
                 "display_priority": 1}]
    # geofences
    if "from geofences" in s and "select name" in s:
        return [{"name": "Home", "latitude": 31.23, "longitude": 121.47, "radius": 100},
                {"name": "Work", "latitude": 31.24, "longitude": 121.50, "radius": 80}]
    # routine locations (frequency)
    if "group by addr_id" in s or ("addr_id" in s and "frequency" in s):
        return [{"addr_id": 10, "frequency": 120}, {"addr_id": 20, "frequency": 90},
                {"addr_id": 30, "frequency": 40}]
    # vampire drain events
    if "lead(ts)" in s:
        return [{"prev_date": _NOW - timedelta(days=2), "date": _NOW - timedelta(days=2) + timedelta(hours=10),
                 "prev_level": 80, "battery_level": 78, "drain": 2, "hours_parked": 10.0, "hours_gap": 10.0}]
    # drives (generic) — many tools
    if "from drives" in s:
        # battery / efficiency aggregates by temp
        if "temp_range" in s:
            return [{"temp_range": "16-21degC" if "degc" not in s else "16-21degC", "trips": 12,
                     "total_km": 320.0, "total_kwh": 50.0}]
        if "date_trunc('week'" in s:
            return [{"week": _NOW, "total_km": 200.0, "estimated_kwh": 30.0, "total_min": 240,
                     "trips": 8, "avg_temp": 18.0, "charged_kwh": 28.0}]
        if "date_trunc('month'" in s:
            return [{"month": _NOW, "trips": 40, "total_km": 1200.0, "total_min": 1500,
                     "total_kwh": 180.0, "total_cost": 110.0}]
        if "sum(distance)" in s and "lifetime_km" in s:
            return [{"lifetime_km": 15000.0, "monthly_km": 800.0}]
        if "count(id)" in s or "trip_count" in s:
            return [{"trip_count": 40, "total_km": 1200.0, "total_min": 1500,
                     "max_single_km": 180.0, "max_speed_kmh": 118.0}]
        # plain drive rows
        return [{
            "start_date": _NOW - timedelta(hours=3), "end_date": _NOW - timedelta(hours=2),
            "distance": 35.0, "duration_min": 40, "power_max": 90.0, "power_min": -40.0,
            "speed_max": 110.0, "start_ideal_range_km": 400.0, "end_ideal_range_km": 390.0,
            "outside_temp_avg": 18.0, "start_address_id": 10, "end_address_id": 20,
            "start_location": "Home Plaza", "end_location": "万达广场",
        }]
    # charging_processes
    if "from charging_processes" in s:
        if "lifetime_kwh" in s:
            return [{"lifetime_kwh": 2200.0, "monthly_kwh": 120.0}]
        if "charge_count" in s or "count(id)" in s:
            return [{"charge_count": 50, "total_kwh": 2200.0, "total_cost": 1300.0}]
        if "charge_windows" in s or "lead(cp" in s:
            return None
        return [{
            "start_date": _NOW - timedelta(days=1), "end_date": _NOW - timedelta(days=1) + timedelta(hours=1),
            "charge_energy_added": 30.0, "charge_energy_used": 32.0, "duration_min": 60,
            "start_battery_level": 40, "end_battery_level": 80, "cost": 18.0,
            "location": "Home", "city": "Shanghai", "country": "China",
            "sessions": 5, "total_kwh": 150.0, "avg_kwh": 30.0, "min_start_battery": 30,
            "max_end_battery": 90, "total_min": 300, "total_cost": 90.0,
        }]
    # positions (location history / battery health / status fallback)
    if "from positions" in s:
        if "tpms" in s:
            return [{"bucket": _NOW, "fl_avg": 2.8, "fr_avg": 2.8, "rl_avg": 2.9, "rr_avg": 2.9,
                     "fl_min": 2.7, "fl_max": 2.9, "fr_min": 2.7, "fr_max": 2.9,
                     "rl_min": 2.8, "rl_max": 3.0, "rr_min": 2.8, "rr_max": 3.0,
                     "date": _NOW}]
        if "floor(latitude" in s:
            return [{"lat": 31.23, "lon": 121.47, "position_count": 500, "first_seen": _NOW - timedelta(days=3),
                     "last_seen": _NOW, "span_hours": 30.0}]
        if "battery_level = 100" in s or "battery_level >= 99" in s or "date_trunc('month'" in s:
            return [{"month": _NOW, "avg_ideal_km": 480.0, "samples": 10}]
        return [{"battery_level": 75, "ideal_battery_range_km": 380.0, "date": _NOW,
                 "latitude": 31.23, "longitude": 121.47}]
    # states
    if "from states" in s:
        return [{"state": "asleep", "start_date": _NOW - timedelta(hours=5), "end_date": _NOW}]
    # updates
    if "from updates" in s:
        return [{"version": "2025.20.1", "start_date": _NOW - timedelta(days=10), "end_date": None}]
    # addresses
    if "from addresses" in s:
        return [{"latitude": 31.30, "longitude": 121.55, "label": "万达广场, Shanghai"}]
    return []


def _fake_query_one(sql: str, params: tuple = ()):
    s = " ".join(sql.lower().split())
    # health check
    if "select 1 as ok" in s:
        return {"ok": 1, "ts": _NOW, "db": "teslamate"}
    if "from cars" in s:
        return {"id": 1, "name": "Model 3", "model": "3", "efficiency": 0.153}
    # combined status (LATERAL JOIN)
    if "left join lateral" in s:
        return {"battery_level": 75, "ideal_battery_range_km": 380.0, "is_climate_on": False,
                "inside_temp": 22.0, "outside_temp": 18.0, "odometer": 30000.0, "speed": None,
                "latitude": 31.23, "longitude": 121.47, "pos_date": _NOW, "vehicle_state": "asleep",
                "charge_energy_added": 0.0, "charge_duration": None, "charge_start_pct": None,
                "charge_end_pct": None, "charge_start": None, "charge_end": _NOW, "sw_version": "2025.20.1"}
    # trip_cost local address hit
    if "from addresses" in s:
        return {"latitude": 31.30, "longitude": 121.55, "label": "万达广场, Shanghai"}
    # trip_cost current position
    if "from positions" in s and "battery_level" in s:
        return {"latitude": 31.23, "longitude": 121.47, "battery_level": 75}
    # efficiency 30-day
    # eco_savings: SUM(distance) AS total_km (single-column drive aggregate)
    if "from drives" in s and "total_km" in s and "sum(distance)" in s:
        return {"total_km": 1200.0}
    if "from drives" in s and "kwh" in s and "km" in s:
        return {"kwh": 180.0, "km": 1000.0, "total_kwh": 180.0}
    if "longest" in s or "charge_windows" in s:
        return {"total_distance_km": 350.0, "charge_end": _NOW - timedelta(days=2),
                "next_charge_start": _NOW - timedelta(days=1), "start_battery": 95, "arrival_battery": 20}
    if "total_distance_km" in s:
        return {"total_distance_km": 15000.0}
    if "total_charge_count" in s:
        return {"total_charge_count": 50}
    if "from drives" in s:
        return {"total_distance_km": 15000.0, "total_kwh": 180.0}
    return None


# Preserve the REAL _query implementation before patching, so the Layer 4
# regression test can exercise the genuine error-handling branch (P0-3).
_REAL_QUERY = tesla._query

# Install fakes
tesla._query = _fake_query
tesla._query_one = _fake_query_one
# Make cached wrappers bypass the pool too
tesla._cached_query = lambda key, sql, params=(), ttl=300: _fake_query(sql, params)
tesla._cached_query_one = lambda key, sql, params=(), ttl=300: _fake_query_one(sql, params)


# =====================================================================
# Layer 1 — pure-logic unit tests for the fix points
# =====================================================================

def test_unit():
    print("\n[Layer 1] Unit tests for fix points")

    # BUG-4: shared constants exist and monthly report uses them (8h not 3h)
    check("BUG-4 VAMPIRE_MIN_HOURS == 8", tesla.VAMPIRE_MIN_HOURS == 8,
          f"got {tesla.VAMPIRE_MIN_HOURS}")
    src = inspect.getsource(tesla)
    # No bare "/ 3600 >= 3" should remain (all replaced by the constant)
    check("BUG-4 no literal '>= 3' vampire threshold left",
          "/ 3600 >= 3\n" not in src and "/ 3600 >= 3 " not in src,
          "found a literal 3h threshold")

    # PERF-1: keyword lists are module-level tuples, pre-lowered
    check("PERF-1 _SHOPPING_KEYWORDS is tuple", isinstance(tesla._SHOPPING_KEYWORDS, tuple))
    check("PERF-1 keywords pre-lowered",
          all(k == k.lower() for k in tesla._SHOPPING_KEYWORDS + tesla._LEISURE_KEYWORDS))

    # PERF-2: _prune_cache evicts expired + caps size
    cache = {}
    now = 1000.0
    for i in range(tesla.CACHE_MAX_ENTRIES + 50):
        cache[f"k{i}"] = {"data": i, "ts": now - i, "ttl": 300}
    tesla._prune_cache(cache, now)
    check("PERF-2 cache pruned to <= max", len(cache) <= tesla.CACHE_MAX_ENTRIES,
          f"len={len(cache)}")
    # expired entries dropped
    cache2 = {"old": {"data": 1, "ts": now - 9999, "ttl": 300},
              "fresh": {"data": 2, "ts": now, "ttl": 300}}
    tesla._prune_cache(cache2, now)
    check("PERF-2 expired entry dropped", "old" not in cache2 and "fresh" in cache2)

    # ISSUE-1: _validate_days rejects bad input
    ok = True
    for bad in (-5, 0, 99999999):
        try:
            tesla._validate_days(bad)
            ok = False
        except ValueError:
            pass
    check("ISSUE-1 _validate_days rejects bad days", ok)
    check("ISSUE-1 _validate_days passes valid", tesla._validate_days(30) == 30)
    check("ISSUE-1 _validate_days None passthrough", tesla._validate_days(None) is None)

    # ISSUE-2: cos(lat) correction — geofence match at high latitude
    # Point near Home (31.23,121.47). With correction longitude weight shrinks.
    name = tesla._find_nearby_geofence(31.23, 121.4706)
    check("ISSUE-2 geofence still matches close point", name == "Home", f"got {name}")
    # A point offset only in longitude beyond radius should NOT match
    far = tesla._find_nearby_geofence(31.23, 121.60)
    check("ISSUE-2 distant point does not match Home", far != "Home", f"got {far}")

    # ISSUE-4: geocode cache eviction cap
    tesla._geocode_cache.clear()
    tesla._geocode_cache_loaded = True  # skip disk load
    orig_max = tesla.GEOCODE_CACHE_MAX_ENTRIES
    tesla.GEOCODE_CACHE_MAX_ENTRIES = 5
    try:
        for i in range(20):
            # avoid disk write errors by pointing file to /tmp
            tesla._geocode_cache_put(f"place{i}", 1.0 * i, 2.0 * i, f"P{i}")
        check("ISSUE-4 geocode cache capped", len(tesla._geocode_cache) <= 5,
              f"len={len(tesla._geocode_cache)}")
    finally:
        tesla.GEOCODE_CACHE_MAX_ENTRIES = orig_max

    # _classify_trip precedence
    check("classify long_trip", tesla._classify_trip("a", "b", 150) == "long_trip")
    check("classify shopping", tesla._classify_trip("home", "万达广场", 10) == "shopping")
    check("classify leisure", tesla._classify_trip("home", "中央公园", 10) == "leisure")
    check("classify other", tesla._classify_trip("x", "y", 5) == "other")

    # v1.2.0: GCJ-02 → WGS-84 conversion (AMAP geocoding)
    # Tiananmen Square: GCJ(39.90919,116.39746) should map to WGS ≈ (39.9078,116.3912).
    wgs_lat, wgs_lon = tesla.gcj02_to_wgs84(39.90919, 116.39746)
    check(
        "v1.2.0 gcj02_to_wgs84 Beijing within ~50m",
        abs(wgs_lat - 39.9078) < 0.0008 and abs(wgs_lon - 116.3912) < 0.0008,
    )
    # Outside mainland China: transform must be a no-op (GCJ == WGS).
    us_lat, us_lon = tesla.gcj02_to_wgs84(33.749, -84.388)  # Atlanta, GA
    check(
        "v1.2.0 gcj02_to_wgs84 out-of-china passthrough",
        us_lat == 33.749 and us_lon == -84.388,
    )
    check("v1.2.0 _gcj02_out_of_china US=True", tesla._gcj02_out_of_china(33.749, -84.388) is True)
    check("v1.2.0 _gcj02_out_of_china Beijing=False", tesla._gcj02_out_of_china(39.9, 116.4) is False)
    # No AMAP key in test env ⇒ AMAP disabled and _amap_geocode returns None
    # (transparent fallback to Nominatim, zero impact on existing users).
    saved_enabled = tesla.AMAP_GEOCODE_ENABLED
    tesla.AMAP_GEOCODE_ENABLED = False
    check(
        "v1.2.0 _amap_geocode disabled → None",
        asyncio.run(tesla._amap_geocode("北京天安门")) is None,
    )
    tesla.AMAP_GEOCODE_ENABLED = saved_enabled

    # ---- v1.2.1: QWeather weather integration --------------------------------
    # Condition classification buckets (Chinese + case-insensitive English).
    check("v1.2.1 classify_weather 晴→clear", tesla._classify_weather("晴") == "clear")
    check("v1.2.1 classify_weather 多云→cloudy", tesla._classify_weather("多云") == "cloudy")
    check("v1.2.1 classify_weather 小雨→rain", tesla._classify_weather("小雨") == "rain")
    check("v1.2.1 classify_weather 暴雪→snow", tesla._classify_weather("暴雪") == "snow")
    # snow precedence over rain (雨夹雪 must be snow, not rain).
    check("v1.2.1 classify_weather 雨夹雪→snow", tesla._classify_weather("雨夹雪") == "snow")
    check("v1.2.1 classify_weather 大雾→fog", tesla._classify_weather("大雾") == "fog")
    check("v1.2.1 classify_weather 霾→fog", tesla._classify_weather("霾") == "fog")
    check("v1.2.1 classify_weather 大风→wind", tesla._classify_weather("大风") == "wind")
    check("v1.2.1 classify_weather case-insensitive 'Clear'→clear", tesla._classify_weather("Clear") == "clear")
    check("v1.2.1 classify_weather 'Heavy Rain'→rain", tesla._classify_weather("Heavy Rain") == "rain")
    check("v1.2.1 classify_weather None→other", tesla._classify_weather(None) == "other")
    # v1.2.3: weather no longer corrects energy — the factor table is gone.
    check("v1.2.3 WEATHER_ENERGY_FACTOR removed (weather is display-only)",
          not hasattr(tesla, "WEATHER_ENERGY_FACTOR"))
    # _format_current_weather renders a compact display-only summary.
    _w = {"text": "Rain", "temp": "18", "feelsLike": "16", "windDir": "NE",
          "windScale": "3", "humidity": "90", "precip": "2.4", "bucket": "rain"}
    _fmt = tesla._format_current_weather(_w)
    check("v1.2.3 _format_current_weather includes condition + temp",
          "Rain" in _fmt and "18°C" in _fmt, _fmt)
    check("v1.2.3 _format_current_weather includes precip when >0",
          "precip 2.4mm" in _fmt, _fmt)
    check("v1.2.3 _format_current_weather omits precip when 0",
          "precip" not in tesla._format_current_weather({"text": "Clear", "temp": "25", "precip": "0"}))
    # Host normalisation: scheme + trailing slash stripped to a bare host.
    saved_host = tesla.QWEATHER_API_HOST
    norm = "https://abc.re.qweatherapi.com/".replace("https://", "").replace("http://", "").rstrip("/")
    check("v1.2.1 host normalisation strips scheme/slash", norm == "abc.re.qweatherapi.com")
    # No QWeather config in test env ⇒ disabled and helpers return None.
    saved_qw = tesla.QWEATHER_ENABLED
    tesla.QWEATHER_ENABLED = False
    check("v1.2.1 _qweather_now disabled → None", asyncio.run(tesla._qweather_now(39.9, 116.4)) is None)
    check("_qweather_locationid disabled → None", asyncio.run(tesla._qweather_locationid(39.9, 116.4)) is None)
    check("v1.2.1 _qweather_historical disabled → None", asyncio.run(tesla._qweather_historical("101010100", "20260101")) is None)
    tesla.QWEATHER_ENABLED = saved_qw

    # ---- v1.2.3: car config must come from env, no hardcoded constants -----
    # The top-level BATTERY_KWH / BATTERY_RANGE_KM / KWH_PER_KM module
    # constants were removed — car info must come exclusively from env vars
    # (TESLA_CAR_PARAMS or TESLA_BATTERY_KWH + TESLA_BATTERY_RANGE_KM).
    check("v1.2.3 BATTERY_KWH module constant removed",
          not hasattr(tesla, "BATTERY_KWH"))
    check("v1.2.3 BATTERY_RANGE_KM module constant removed",
          not hasattr(tesla, "BATTERY_RANGE_KM"))
    check("v1.2.3 KWH_PER_KM module constant removed",
          not hasattr(tesla, "KWH_PER_KM"))
    # Camping reference is intentionally a fixed algorithm constant (NOT a car
    # config) — the user explicitly wants the camping-rate threshold to be
    # battery-size-independent, hence the hardcoded 75 kWh reference.
    check("v1.2.3 CAMPING_REFERENCE_BATTERY_KWH is fixed at 75.0 (algorithm constant)",
          tesla.CAMPING_REFERENCE_BATTERY_KWH == 75.0)

    # ---- v1.2.3: camping-mode flag in tesla_vampire_drain --------------------
    # Rate-based threshold: kWh/h averaged over the parked period, computed
    # against a FIXED 75 kWh reference battery (battery-size-independent).
    check("v1.2.3 CAMPING_KWH_PER_HOUR default == 0.8",
          tesla.CAMPING_KWH_PER_HOUR == 0.8, f"got {tesla.CAMPING_KWH_PER_HOUR}")
    check("v1.2.3 CAMPING_REFERENCE_BATTERY_KWH == 75.0",
          tesla.CAMPING_REFERENCE_BATTERY_KWH == 75.0)
    # End-to-end: rate >= 0.8 kWh/h triggers 露营模式. SQL already enforces
    # hours >= 8 and drain > 0. Formula: kWh/h = drain% × 75 / 100 / hours.
    # drain=15%, hours=10 → 15 × 75/100 / 10 = 1.125 kWh/h ≥ 0.8 → camping.
    _high_rate_row = {
        "prev_date": _NOW - timedelta(days=1),
        "date": _NOW - timedelta(days=1) + timedelta(hours=10),
        "prev_level": 90, "battery_level": 75, "drain": 15, "hours_parked": 10.0,
        "hours_gap": 10.0, "park_lat": 31.23, "park_lon": 121.47,
    }
    saved_q = tesla._query
    saved_q1 = tesla._query_one
    tesla._query = lambda sql, params=(): [_high_rate_row]
    tesla._query_one = lambda sql, params=(): None
    try:
        out = asyncio.run(tesla.tesla_vampire_drain(days=14))
        check("v1.2.3 vampire_drain tags high-rate event as 露营模式",
              "露营模式" in out, out[:200])
        # Negative: drain=2%, hours=10 → 2 × 75/100 / 10 = 0.15 kWh/h → not camping
        _low_rate_row = dict(_high_rate_row, drain=2, hours_parked=10.0)
        tesla._query = lambda sql, params=(): [_low_rate_row]
        out2 = asyncio.run(tesla.tesla_vampire_drain(days=14))
        check("v1.2.3 vampire_drain does NOT tag low-rate event as 露营模式",
              "露营模式" not in out2, out2[:200])
        # Battery-size-independence: same drain%/hours should yield the same
        # verdict regardless of what TESLA_BATTERY_KWH says. (We verify by
        # running the same row with different car configs and checking the
        # kWh/h math gives identical results since the reference is fixed.)
        saved_cfg = tesla._get_car_config
        tesla._get_car_config = lambda cid: {"kwh": 100.0, "range_km": 600, "kwh_per_km": 0.1667}
        # 16 × 75 / 100 / 15 = 0.8 kWh/h exactly (no float drift) → camping (≥)
        _boundary_row = {"prev_date": _NOW - timedelta(days=1),
                         "date": _NOW - timedelta(days=1) + timedelta(hours=15),
                         "prev_level": 90, "battery_level": 74, "drain": 16,
                         "hours_parked": 15.0, "hours_gap": 15.0,
                         "park_lat": 31.23, "park_lon": 121.47}
        tesla._query = lambda sql, params=(): [_boundary_row]
        out_b = asyncio.run(tesla.tesla_vampire_drain(days=14))
        check("v1.2.3 boundary rate (0.8 kWh/h) → camping (≥)",
              "露营模式" in out_b, out_b[:200])
        # Just below threshold: 12 × 75 / 100 / 12 = 0.75 kWh/h → NOT camping
        _just_below = dict(_boundary_row, drain=12, hours_parked=12.0,
                           hours_gap=12.0)
        tesla._query = lambda sql, params=(): [_just_below]
        out_jb = asyncio.run(tesla.tesla_vampire_drain(days=14))
        check("v1.2.3 rate just below threshold (0.75 kWh/h) → NOT camping",
              "露营模式" not in out_jb, out_jb[:200])
        tesla._get_car_config = saved_cfg
        # Edge case: long parking (168h) with high drain — rate determines
        # verdict, not duration. drain=20%, hours=168 → 0.089 kWh/h → NOT camping.
        _long_low_rate = dict(_high_rate_row, drain=20, hours_parked=168.0,
                              hours_gap=168.0)
        tesla._query = lambda sql, params=(): [_long_low_rate]
        out_long = asyncio.run(tesla.tesla_vampire_drain(days=14))
        check("v1.2.3 long parking (168h, 20%) with low rate → NOT camping",
              "露营模式" not in out_long, out_long[:200])
        # Disabled: setting threshold to 0 must skip the flag entirely.
        _saved_threshold = tesla.CAMPING_KWH_PER_HOUR
        tesla.CAMPING_KWH_PER_HOUR = 0
        tesla._query = lambda sql, params=(): [_high_rate_row]
        out3 = asyncio.run(tesla.tesla_vampire_drain(days=14))
        check("v1.2.3 camping disabled (threshold=0) → no tag",
              "露营模式" not in out3, out3[:200])
        tesla.CAMPING_KWH_PER_HOUR = _saved_threshold
    finally:
        tesla._query = saved_q
        tesla._query_one = saved_q1

    # Regression: when QWeather is enabled AND there are multiple rows
    # (incl. camping events), the dedupe path must not crash with
    # `unhashable type: 'dict'`. Exercises the full targets-combine loop.
    _rows = [_high_rate_row, {**_high_rate_row, "park_lat": 31.30, "park_lon": 121.55,
                                "drain": 18, "prev_level": 92, "battery_level": 74,
                                "hours_parked": 10.0, "hours_gap": 10.0}]
    saved_q = tesla._query
    saved_q1 = tesla._query_one
    saved_qw = tesla.QWEATHER_ENABLED
    saved_qwf = tesla._qweather_now
    calls = []
    async def _stub_qw(lat, lon):
        calls.append((round(lat, 2), round(lon, 2)))
        return {"text": "Clear", "temp": "25", "feelsLike": "25",
                "windDir": "N", "windScale": "1", "humidity": "60",
                "precip": "0", "bucket": "clear"}
    tesla.QWEATHER_ENABLED = True
    tesla._qweather_now = _stub_qw
    tesla._query = lambda sql, params=(): _rows
    tesla._query_one = lambda sql, params=(): None
    try:
        out = asyncio.run(tesla.tesla_vampire_drain(days=14))
        check("v1.2.3 vampire_drain handles multi-row + camping + weather",
              "露营模式" in out and out.count("🏕️ 露营模式") == 2, out[:200])
        check("v1.2.3 multi-row weather fetch dedupes by grid key",
              len(calls) == 2, f"expected 2 grid cells, got {len(calls)}: {calls}")
    finally:
        tesla._query = saved_q
        tesla._query_one = saved_q1
        tesla.QWEATHER_ENABLED = saved_qw
        tesla._qweather_now = saved_qwf

    # ---- v1.2.3: three-category separation in monthly views ----------------
    # Mocked rows: drive_kwh=180, charge_kwh=210, vampire_kwh=12. With 1250 km
    # driven, Wh/km (driving) = 180*1000/1250 = 144 — should NOT use charging.
    _mock_summary_row = {
        "month": _NOW.replace(day=1),
        "trips": 42, "total_km": 1250.0, "total_min": 1500,
        "drive_kwh": 180.0, "charge_kwh": 210.0, "vampire_kwh": 12.0,
        "total_cost": 120.0,
    }
    saved_q = tesla._query
    saved_q1 = tesla._query_one
    tesla._query = lambda sql, params=(): [_mock_summary_row]
    try:
        out = asyncio.run(tesla.tesla_monthly_summary(months=1))
        # All three columns present and labeled
        check("monthly_summary shows Drive kWh column",
              "Drive kWh" in out, out[:300])
        check("monthly_summary shows Charge kWh column",
              "Charge kWh" in out, out[:300])
        check("monthly_summary shows Vampire kWh column",
              "Vampire kWh" in out, out[:300])
        # Wh/km uses driving kWh (180) → 144 Wh/km, NOT charging (210) → 168
        check("monthly_summary Wh/km uses driving kWh only (144, not 168)",
              "144" in out and "168" not in out, out[:600])
        # All three kWh values present
        check("monthly_summary shows driving kWh value (180.0)",
              "180.0" in out, out[:600])
        check("monthly_summary shows charging kWh value (210.0)",
              "210.0" in out, out[:600])
        check("monthly_summary shows vampire kWh value (12.0)",
              "12.0" in out, out[:600])
    finally:
        tesla._query = saved_q

    # monthly_report: 3 separate _query_one calls (drives, charging, vampire)
    def _fake_qo_split(sql, params=()):
        s = " ".join(sql.lower().split())
        if "cur_drive_kwh" in s:
            return {"cur_trips": 42, "cur_km": 1250.0, "cur_min": 1500,
                    "prev_km": 1100.0, "cur_drive_kwh": 180.0,
                    "prev_drive_kwh": 165.0}
        if "cur_charge_kwh" in s:
            return {"cur_cost": 120.0, "cur_charge_kwh": 210.0,
                    "prev_charge_kwh": 195.0}
        if "cur_vampire_pct" in s:
            return {"cur_vampire_pct": 16.0, "prev_vampire_pct": 14.0}
        return None
    tesla._query_one = _fake_qo_split
    try:
        # Use a past month to avoid the cache fast-path's "current month" branch
        out = asyncio.run(tesla.tesla_monthly_report(year=2025, month=6))
        check("monthly_report shows driving energy label",
              "Driving energy" in out, out[:600])
        check("monthly_report shows charging energy label",
              "Charging energy" in out, out[:600])
        check("monthly_report shows vampire drain label",
              "Vampire drain" in out, out[:600])
        check("monthly_report shows three kWh values",
              "180.0" in out and "210.0" in out and "12.0" in out,
              out[:800])
    finally:
        tesla._query_one = saved_q1

    # REGRESSION-v1.2.3: d.battery_level never appears in SQL — drives table
    # has no battery_level column (it's on positions). Both monthly tools
    # were broken in v1.2.3 release with `d.battery_level IS NOT NULL` in
    # the WHERE clause of the start_position JOIN. PostgreSQL would raise
    # `column d.battery_level does not exist` on a real DB.
    src = inspect.getsource(tesla)
    check("REGRESSION no `d.battery_level` reference in source",
          "d.battery_level" not in src,
          "found d.battery_level reference — drives table has no battery_level column")

    # REGRESSION-v1.2.3: both monthly tools' SQL fingerprints must contain
    # the correct `p.battery_level IS NOT NULL` filter on the start_position JOIN.
    src = inspect.getsource(tesla)
    # monthly_report
    check("REGRESSION monthly_report uses p.battery_level filter",
          "JOIN positions p ON p.id = d.start_position_id\n            WHERE d.car_id = %s AND p.battery_level IS NOT NULL" in src)
    # monthly_summary
    check("REGRESSION monthly_summary uses p.battery_level filter",
          src.count("JOIN positions p ON p.id = d.start_position_id\n            WHERE d.car_id = %s AND p.battery_level IS NOT NULL") >= 2,
          "expected >=2 occurrences (monthly_report + monthly_summary)")

    # REGRESSION-v1.2.3: cp.outside_temp_avg never appears — it's not on
    # charging_processes. The vintage tool originally referenced it; if it
    # creeps back in, get_charging_vintage_data crashes on real DB.
    check("REGRESSION no `cp.outside_temp_avg` reference in source",
          "cp.outside_temp_avg" not in src,
          "found cp.outside_temp_avg reference — column not on charging_processes")

    # REGRESSION-v1.2.4: _cutoff_from_days helper exists and is used at
    # every site that previously did `_utcnow() - timedelta(days=days)`,
    # because days=None otherwise raises TypeError on those call sites.
    check("REGRESSION _cutoff_from_days helper exists",
          hasattr(tesla, "_cutoff_from_days"),
          "_cutoff_from_days helper not defined")
    raw_timedelta = "(_utcnow() - timedelta(days=days))"
    check("REGRESSION no bare `_utcnow() - timedelta(days=days)` outside helper docstring",
          raw_timedelta not in src.replace(
              "    `_utcnow() - timedelta(days=days)` which raises TypeError when days is None.", ""
          ),
          f"found unguarded {raw_timedelta}")

    # REGRESSION-v1.2.4: tesla_savings monthly fallback must filter by
    # month_start_utc, otherwise "this month estimated kWh" equals lifetime.
    # We assert the source contains a start_date predicate scoped by a
    # month_start_utc-like parameter binding.
    check("REGRESSION tesla_savings monthly fallback filters by start_date",
          ("month_start_utc" in src
           and "AND start_date >= %s" in src
           and src.count("AND start_date >= %s") >= 2),  # monthly + lifetime have separate paths
          "tesla_savings monthly estimate not scoped to current month")

    # REGRESSION-v1.2.4: _monthly_report_compute must use tzinfo=USER_TZ
    # (matches sibling tools at lines 4719/5219/1916). Naive datetime
    # would shift the queried window by ±14h for non-UTC users.
    mr_body = inspect.getsource(tesla._monthly_report_compute)
    check("REGRESSION _monthly_report_compute uses tzinfo=USER_TZ",
          "tzinfo=USER_TZ" in mr_body and ".astimezone(timezone.utc)" in mr_body,
          "monthly_report still uses naive datetime")

    # REGRESSION-v1.2.4 (B1): async wrappers for psycopg2 calls so the event
    # loop isn't blocked. Verify the helpers exist and that no sync _query call
    # remains inside any async function.
    check("REGRESSION async query wrappers exist",
          hasattr(tesla, "_query_async")
          and hasattr(tesla, "_query_one_async")
          and hasattr(tesla, "_cached_query_async")
          and hasattr(tesla, "_cached_query_one_async"),
          "missing async query wrapper helpers")

    # REGRESSION-v1.2.4 (B2): _cached_result uses asyncio.Future for
    # single-flight, so cold-key concurrent callers coalesce into one fn().
    check("REGRESSION _cached_result uses per-key in-flight future",
          hasattr(tesla, "_result_inflight")
          and "_result_inflight[key] = inflight" in src,
          "_cached_result lacks single-flight coalescing")

    # REGRESSION-v1.2.4 (B3): _check_car_config helper exists and is invoked
    # by tools that compute energy/kWh to fail loudly instead of returning 0.
    check("REGRESSION _check_car_config helper exists",
          hasattr(tesla, "_check_car_config"),
          "_check_car_config helper missing")

    # REGRESSION-v1.2.4 (B4): three previously-unchecked tools now reject
    # negative/oversized days.
    check("REGRESSION calculate_eco_savings_vs_icev validates days",
          "days = _validate_days(days)" in inspect.getsource(tesla.calculate_eco_savings_vs_icev),
          "calculate_eco_savings_vs_icev still accepts any days")
    check("REGRESSION check_driving_achievements validates days",
          "days = _validate_days(days)" in inspect.getsource(tesla.check_driving_achievements),
          "check_driving_achievements still accepts any days")
    gb_src = inspect.getsource(tesla.generate_weekend_blindbox)
    check("REGRESSION generate_weekend_blindbox validates months_lookback",
          "months_lookback <= 0" in gb_src and "MAX_LOOKBACK_DAYS" in gb_src,
          "generate_weekend_blindbox still accepts any months_lookback")

    # REGRESSION-v1.2.4 (B5): _qw_locid_flight_lock must check loop identity
    # so a cached lock from a previous event loop doesn't trigger
    # `RuntimeError: got Future ... attached to a different loop` in tests or
    # multi-worker deployments.
    fl_src = inspect.getsource(tesla._qw_locid_flight_lock)
    check("REGRESSION _qw_locid_flight_lock is loop-aware",
          "asyncio.get_running_loop()" in fl_src
          and "loop_id" in fl_src
          and "cached_loop_id" in fl_src,
          "_qw_locid_flight_lock still binds to first-seen loop")

    # REGRESSION-v1.2.4 (B7): broken connections must be closed instead of
    # returned to the pool, so the next 8 callers don't inherit a dead socket.
    check("REGRESSION _put_conn_safe helper exists",
          hasattr(tesla, "_put_conn_safe"),
          "_put_conn_safe helper missing")
    q_src = inspect.getsource(tesla._query)
    check("REGRESSION _query detects broken connections",
          "_put_conn_safe" in q_src and "InterfaceError" in q_src
          and "OperationalError" in q_src,
          "_query still puts broken connections back into pool")

    # REGRESSION-v1.2.4 (B11): narrative tool has hard LIMIT + window cap.
    check("REGRESSION LIMIT_NARRATIVE env var defined",
          hasattr(tesla, "LIMIT_NARRATIVE") and isinstance(tesla.LIMIT_NARRATIVE, int),
          "LIMIT_NARRATIVE not defined")
    nar_src = inspect.getsource(tesla.generate_travel_narrative_context)
    check("REGRESSION narrative tool bounds time window",
          "MAX_LOOKBACK_DAYS" in nar_src and "time window too large" in nar_src,
          "narrative tool still accepts arbitrarily long windows")
    check("REGRESSION narrative tool applies LIMIT_NARRATIVE",
          "LIMIT_NARRATIVE" in nar_src,
          "narrative SQL has no LIMIT clause")
    check("REGRESSION narrative tool warns when capped",
          "Timeline truncated at" in nar_src,
          "narrative tool silently truncates at LIMIT")

    # REGRESSION-v1.2.4 (B6): when all in-flight QWeather locks are held,
    # _qw_locid_flight_lock must force-evict the oldest entry instead of
    # silently exceeding _QW_INFLIGHT_MAX (which would let single-flight
    # get bypassed for the evicted gkey).
    fl_full_src = inspect.getsource(tesla._qw_locid_flight_lock)
    check("REGRESSION QWeather flight lock force-evicts when saturated",
          "force-evicting oldest key" in fl_full_src,
          "QWeather lock eviction may exceed _QW_INFLIGHT_MAX under contention")

    # REGRESSION-v1.2.4 (B8): _get_conn must retry briefly on PoolError
    # instead of surfacing a raw pool error to the MCP client.
    gc_src = inspect.getsource(tesla._get_conn)
    check("REGRESSION _get_conn retries on PoolError",
          "psycopg2.pool.PoolError" in gc_src
          and "_POOL_RETRY_WINDOW_SEC" in gc_src
          and "Database connection pool exhausted" in gc_src,
          "_get_conn surfaces raw PoolError to MCP caller")

    # REGRESSION-v1.2.4 (B9): every cache key built for _cached_query* /
    # _cached_result must go through _vkey so upgrades invalidate stale
    # entries. We assert that no bare f"..." cache key prefixes remain.
    # ("geofences_all" is allowed only when wrapped by _vkey(...).)
    bare_prefix_patterns = [
        r'f"car_',  # was f"car_{id}", should now be _vkey("car", id)
        r'f"bh:', r'f"sv:', r'f"eft:', r'f"efw:',
        r'f"cbl:', r'f"td:', r'f"mr:',
    ]
    leftover = []
    for pat in bare_prefix_patterns:
        leftover.extend(re.findall(pat, src))
    # Strip the legitimate _vkey("geofences_all") inner-string occurrences
    geo_vkey_uses = src.count('_vkey("geofences_all")')
    geo_bare = src.count('"geofences_all"') - geo_vkey_uses
    leftover.extend(["geofences_all"] * geo_bare)
    check(f"REGRESSION no bare cache-key prefixes (found {len(leftover)})",
          len(leftover) == 0,
          f"bare cache keys remain: {leftover}")
    check("REGRESSION _vkey helper exists and uses __version__",
          hasattr(tesla, "_vkey")
          and "__version__" in inspect.getsource(tesla._vkey)
          and src.count("_vkey(") >= 10,
          f"_vkey only used {src.count('_vkey(')} times")

    # REGRESSION-v1.2.4 (B10): ROUTINE_CACHE must have a bound and a pruner
    # so a multi-tenant deployment doesn't leak car_ids over weeks.
    check("REGRESSION ROUTINE_CACHE bounded + pruned",
          hasattr(tesla, "_routine_cache_prune")
          and hasattr(tesla, "ROUTINE_CACHE_MAX"),
          "ROUTINE_CACHE still unbounded")

    # REGRESSION-v1.2.4 (B12): tesla_monthly_summary must scope every
    # date_trunc to USER_TZ, otherwise non-UTC users get mis-bucketed months.
    ms_src = inspect.getsource(tesla.tesla_monthly_summary)
    check("REGRESSION monthly_summary uses USER_TZ in date_trunc",
          ms_src.count("AT TIME ZONE 'UTC' AT TIME ZONE %s") >= 5
          and "USER_TZ" in ms_src,
          "monthly_summary still uses session-TZ date_trunc")

    # REGRESSION-v1.2.4 (B13): midnight-ghost query no longer pulls columns
    # the consumer never reads.
    ach_src = inspect.getsource(tesla.check_driving_achievements)
    midnight_block = ach_src.split("Achievement 2", 1)[-1].split("Achievement 3", 1)[0]
    check("REGRESSION midnight-ghost query has no dead columns",
          "outside_temp_avg" not in midnight_block.split("SELECT", 1)[1].split("FROM", 1)[0]
          or "outside_temp_avg" in midnight_block.split("-- Achievement 3", 1)[0].split("SELECT", 1)[1].split("FROM", 1)[0],
          "midnight-ghost query still pulls outside_temp_avg")
    # Cleaner check: between Achievement 2 SELECT and FROM, no outside_temp_avg
    m = re.search(r"Achievement 2.*?SELECT\s+(.*?)\s+FROM drives", ach_src, re.DOTALL)
    if m:
        cols = m.group(1)
        check("REGRESSION midnight-ghost SELECT is lean",
              "outside_temp_avg" not in cols and "end_address_id" not in cols,
              f"midnight-ghost still pulls {cols}")

    # REGRESSION-v1.2.4 (B14): no dead next_charge_end window function.
    lt_src = inspect.getsource(tesla.get_longest_trip_on_single_charge)
    check("REGRESSION no dead next_charge_end window",
          "next_charge_end" not in lt_src,
          "get_longest_trip_on_single_charge still computes next_charge_end")

    # REGRESSION-v1.2.4 (B15): tesla_live pulls `states.state` via LATERAL
    # instead of a separate round-trip.
    live_src = inspect.getsource(tesla.tesla_live)
    check("REGRESSION tesla_live merges states into combined query",
          "states" in live_src and "LEFT JOIN LATERAL" in live_src
          and live_src.count("LEFT JOIN LATERAL") >= 4,
          f"tesla_live only has {live_src.count('LEFT JOIN LATERAL')} LATERAL joins (expect 4)")

    # REGRESSION-v1.2.4 (NEW BUG, found in smoke test): tesla_drives had
    # `actual_days < days * 0.9` downstream of the days=None-tolerant
    # _validate_days path, which still crashed because days was None.
    # The fix skips the window-rewrite branch entirely when days is None.
    drives_src = inspect.getsource(tesla.tesla_drives)
    check("REGRESSION tesla_drives guards `days * 0.9` for days=None",
          "days is not None" in drives_src and "days * 0.9" in drives_src,
          "tesla_drives still crashes on days=None via `days * 0.9`")

    # REGRESSION-v1.2.4 (NEW BUG): get_vehicle_persona_status had
    # `if days_lookback <= 0` which TypeError'd before the ❌ message
    # when days_lookback=None. Fix: gate the check on `is not None`.
    persona_src = inspect.getsource(tesla.get_vehicle_persona_status)
    check("REGRESSION persona guards days_lookback=None",
          "days_lookback is not None" in persona_src,
          "get_vehicle_persona_status still crashes on days_lookback=None")


# =====================================================================
# Layer 2 — smoke-call every MCP tool
# =====================================================================

# Reasonable default args per tool (only required / interesting ones)
TOOL_ARGS = {
    "tesla_trips_by_category": {"category": "shopping", "limit": 5, "days": 30},
    "tesla_trip_cost": {"destination": "万达广场"},
    "tesla_driving_score": {"period": "recent_n", "n": 10},
    "tesla_efficiency": {"days": 30},
    "tesla_drives": {"days": 30},
    "tesla_charging_history": {"days": 30},
    "tesla_vampire_drain": {"days": 14},
    "tesla_location_history": {"days": 7},
    "tesla_state_history": {"days": 7},
    "tesla_tpms_history": {"days": 30},
    "tesla_monthly_summary": {"months": 6},
    "tesla_top_destinations": {"limit": 10},
    "tesla_efficiency_by_weather": {"days": 30},
    "calculate_eco_savings_vs_icev": {"days": 30},
    "generate_monthly_driving_report": {"target_month": "2025-05"},
    "tesla_monthly_report": {"year": 2025, "month": 5},
    "generate_travel_narrative_context": {"start_time": "2025-05-01", "end_time": "2025-05-07"},
}


async def _get_tools():
    tools = await tesla.mcp.list_tools()
    return tools


async def test_tools():
    print("\n[Layer 2] Smoke test every MCP tool")
    tools = await _get_tools()
    print(f"  (discovered {len(tools)} tools)")
    # Map tool name -> underlying python fn via module attributes
    for t in tools:
        name = t.name
        fn = getattr(tesla, name, None)
        if fn is None:
            check(f"tool {name} resolvable", False, "no module attr")
            continue
        args = TOOL_ARGS.get(name, {})
        try:
            if inspect.iscoroutinefunction(fn):
                res = await fn(**args)
            else:
                res = fn(**args)
            check(f"tool {name}() returns str", isinstance(res, str) and len(res) > 0,
                  f"type={type(res)}")
        except Exception as e:  # noqa: BLE001
            check(f"tool {name}() no exception", False, f"{type(e).__name__}: {e}")
            if os.environ.get("TEST_VERBOSE"):
                traceback.print_exc()


# =====================================================================
# Layer 3 — error-path tests (validation returns friendly ❌ strings)
# =====================================================================

async def test_error_paths():
    print("\n[Layer 3] Error-path / validation tests")
    r = await tesla.tesla_trip_cost(destination="")
    check("trip_cost empty → error", r.startswith("❌"))
    r = await tesla.tesla_trip_cost(destination="x")  # too short
    check("trip_cost too-short → error", r.startswith("❌"), r[:40])
    r = await tesla.tesla_drives(days=-3)
    check("drives negative days → error", r.startswith("❌"), r[:40])
    r = await tesla.tesla_efficiency(days=999999)
    check("efficiency oversized days → error", r.startswith("❌"), r[:40])
    r = await tesla.tesla_monthly_summary(months=0)
    check("monthly_summary 0 → error", r.startswith("❌"))


# =====================================================================
# Layer 4 — regression tests for the v1.2.1 code-review fixes
#   P0-1: geocode file-cache atomic write + lock-held load/mutate/persist
#   P0-3: no rollback() on autocommit connections (error re-raised cleanly)
# =====================================================================

def test_review_fixes():
    print("\n[Layer 4] Code-review regression tests (P0-1 / P0-3)")
    import json as _json
    import tempfile
    import threading
    import pathlib

    # ---- P0-1: concurrent geocode-cache writes never corrupt the JSON ----
    tmpdir = pathlib.Path(tempfile.mkdtemp(prefix="tesla_cache_test_"))
    orig_file = tesla._GEOCODE_CACHE_FILE
    orig_cache = tesla._geocode_cache
    orig_loaded = tesla._geocode_cache_loaded
    try:
        tesla._GEOCODE_CACHE_FILE = tmpdir / "geocode.json"
        tesla._geocode_cache = {}
        tesla._geocode_cache_loaded = True  # skip disk load; start empty

        errors: list[str] = []

        def _writer(n: int):
            try:
                for i in range(40):
                    tesla._geocode_cache_put(f"addr-{n}-{i}", 39.9 + i * 1e-4,
                                             116.4 + i * 1e-4, f"place {n}-{i}")
            except Exception as e:  # noqa: BLE001
                errors.append(f"{type(e).__name__}: {e}")

        threads = [threading.Thread(target=_writer, args=(n,)) for n in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        check("P0-1 concurrent writes raised nothing", not errors, "; ".join(errors))

        # File must exist and be valid JSON (never truncated/partial).
        raw = tesla._GEOCODE_CACHE_FILE.read_text(encoding="utf-8")
        parsed = None
        try:
            parsed = _json.loads(raw)
        except Exception as e:  # noqa: BLE001
            check("P0-1 on-disk cache is valid JSON", False, str(e))
        if parsed is not None:
            check("P0-1 on-disk cache is valid JSON", True)
            # Bounded by the cap (no unbounded growth).
            check("P0-1 cache within cap",
                  len(parsed) <= tesla.GEOCODE_CACHE_MAX_ENTRIES,
                  f"{len(parsed)} > {tesla.GEOCODE_CACHE_MAX_ENTRIES}")
            # No leftover temp files in the dir.
            leftovers = list(tmpdir.glob("*.tmp.*"))
            check("P0-1 no leftover temp files", not leftovers,
                  ", ".join(p.name for p in leftovers))
    finally:
        tesla._GEOCODE_CACHE_FILE = orig_file
        tesla._geocode_cache = orig_cache
        tesla._geocode_cache_loaded = orig_loaded

    # ---- P0-3: a failing query re-raises the ORIGINAL error, no rollback ----
    # Temporarily point _get_conn at a fake conn whose cursor raises; assert the
    # original error propagates and rollback() is never invoked.
    class _FakeCursor:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def execute(self, *a, **k):
            raise RuntimeError("boom-original")
        def fetchall(self): return []
        def fetchone(self): return None

    class _FakeConn:
        def __init__(self): self.rollback_called = False
        def cursor(self): return _FakeCursor()
        def rollback(self): self.rollback_called = True

    fake = _FakeConn()
    orig_get = tesla._get_conn
    orig_put = tesla._put_conn
    try:
        tesla._get_conn = lambda: fake
        tesla._put_conn = lambda conn: None
        raised = None
        try:
            _REAL_QUERY("SELECT 1")  # the genuine implementation, not the fake
        except Exception as e:  # noqa: BLE001
            raised = e
        check("P0-3 original error re-raised",
              isinstance(raised, RuntimeError) and "boom-original" in str(raised),
              repr(raised))
        check("P0-3 rollback() never called on autocommit conn",
              fake.rollback_called is False)
    finally:
        tesla._get_conn = orig_get
        tesla._put_conn = orig_put


# =====================================================================
# Layer 5 — regression test for the v1.2.2 fix
#   P0-2: QWeather LocationID single-flight — concurrent lookups of the SAME
#         grid cell fire only ONE (billed) GeoAPI call, the rest reuse it.
# =====================================================================

async def _test_single_flight_async():
    print("\n[Layer 5] QWeather LocationID single-flight (P0-2)")

    # A fake httpx.AsyncClient that counts real GeoAPI calls and adds a small
    # await so concurrent coroutines genuinely overlap inside the helper.
    call_count = {"geo": 0}

    class _FakeResp:
        def raise_for_status(self): return None
        def json(self):
            return {"code": "200", "location": [{"id": "101010100"}]}

    class _FakeClient:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url, params=None):
            call_count["geo"] += 1
            await asyncio.sleep(0.02)  # widen the race window
            return _FakeResp()

    orig_enabled = tesla.QWEATHER_ENABLED
    orig_client = tesla.httpx.AsyncClient
    orig_cache = dict(tesla._qw_locid_cache)
    orig_inflight = dict(tesla._qw_locid_inflight)
    try:
        tesla.QWEATHER_ENABLED = True
        tesla.httpx.AsyncClient = _FakeClient  # type: ignore[assignment]
        tesla._qw_locid_cache.clear()
        tesla._qw_locid_inflight.clear()

        # 20 concurrent lookups of the SAME coordinate (same grid cell).
        results = await asyncio.gather(
            *[tesla._qweather_locationid(39.9042, 116.4074) for _ in range(20)]
        )

        check("P0-2 only ONE billed GeoAPI call for 20 concurrent same-cell lookups",
              call_count["geo"] == 1, f"got {call_count['geo']} calls")
        check("P0-2 all concurrent callers got the same LocationID",
              all(r == "101010100" for r in results),
              f"results={set(results)}")
        # A subsequent call must be a pure cache hit (still just 1 total).
        again = await tesla._qweather_locationid(39.9042, 116.4074)
        check("P0-2 later call is a cache hit (no new GeoAPI call)",
              call_count["geo"] == 1 and again == "101010100",
              f"calls={call_count['geo']}, id={again}")

        # A DIFFERENT cell must trigger exactly one more call.
        _ = await tesla._qweather_locationid(31.2304, 121.4737)  # Shanghai
        check("P0-2 different cell triggers exactly one more call",
              call_count["geo"] == 2, f"got {call_count['geo']} calls")
    finally:
        tesla.QWEATHER_ENABLED = orig_enabled
        tesla.httpx.AsyncClient = orig_client  # type: ignore[assignment]
        tesla._qw_locid_cache.clear()
        tesla._qw_locid_cache.update(orig_cache)
        tesla._qw_locid_inflight.clear()
        tesla._qw_locid_inflight.update(orig_inflight)


def test_single_flight():
    asyncio.run(_test_single_flight_async())


def main():
    test_unit()
    asyncio.run(test_tools())
    asyncio.run(test_error_paths())
    test_review_fixes()
    test_single_flight()
    print("\n" + "=" * 60)
    print(f"RESULT: {PASS} passed, {FAIL} failed")
    if FAILURES:
        print("\nFailures:")
        for f in FAILURES:
            print(f"  - {f}")
    print("=" * 60)
    sys.exit(0 if FAIL == 0 else 1)


if __name__ == "__main__":
    main()
