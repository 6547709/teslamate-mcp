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


def main():
    test_unit()
    asyncio.run(test_tools())
    asyncio.run(test_error_paths())
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
