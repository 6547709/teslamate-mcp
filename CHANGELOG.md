# 更新日志 / Changelog

> **语言 / Language**: 默认中文（Default: 中文）。每个版本条目先列中文，再列英文。
> Each release entry lists **中文 first, English second**. 历史版本（v1.2.2 及之前）仅英文，v1.2.3 起转为双语。

所有重要变更都会记录在此文件。

格式遵循 [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)，版本号遵循 [Semantic Versioning](https://semver.org/spec/v2.0.0.html)。

All notable changes are documented in this file. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.2.4] - 2026-07-17

### 中文

稳定性与正确性补丁版本 —— **0 项数据库改动**。本版本修复 **22 个 bug**，覆盖 SQL schema 错列、时区错位、None/负值静默崩溃、HTTP 模式性能问题、缓存安全等。全部修复均为只读 SELECT 查询文本优化或 Python 逻辑改进，可直接 `git pull` 升级，无需迁移或停机。

#### Bug 修复

**SQL schema 错列（2 项）**

- `tesla_monthly_report` / `tesla_monthly_summary` 在 `events` CTE 的第 2 条 `UNION ALL` 分支里错误引用了 `d.battery_level` —— `drives` 表没有此列，运行时直接 `column does not exist`。已改为 `p.battery_level`（JOIN positions 后）。
- `get_charging_vintage_data` 引用了 `cp.outside_temp_avg` —— `charging_processes` 表没有此列（它在 `drives` 上）。已删除该字段，改为 `LEFT JOIN LATERAL positions` 按时间倒序取最近一条非空温度补回温度信息。

**时区与单位（3 项）**

- `tesla_monthly_report` 月份边界用 naive `datetime(year, month, 1)`，非 UTC 用户（如 `Asia/Shanghai`）的窗口被偏 ±14h。已改为 `datetime(..., tzinfo=USER_TZ).astimezone(timezone.utc)`，与兄弟工具对齐。
- `tesla_monthly_summary` 的 `date_trunc('month', start_date)` 依赖 PG session TZ。已改为 `date_trunc('month', start_date AT TIME ZONE 'UTC' AT TIME ZONE %s)` 显式绑 USER_TZ。
- `tesla_weather` 当 QWeather API 缺 `temp`/`feelsLike` 时显示 `None°C` / `None°F`。已加 `if temp_c is not None` 守卫。

**输入校验与崩溃（5 项）**

- 9 个工具（`tesla_charging_history`、`tesla_drives`、`tesla_efficiency`、`tesla_location_history`、`tesla_state_history`、`tesla_tpms_history`、`tesla_vampire_drain`、`tesla_efficiency_by_weather`、`tesla_trips_by_category`）在 `days=None` 时崩 `TypeError: timedelta(days=None)`。新增 `_cutoff_from_days(None)` helper，None 自动落到 MAX_LOOKBACK_DAYS。
- `calculate_eco_savings_vs_icev`、`check_driving_achievements` 完全没有 `days` 校验。已加 `_validate_days`。
- `generate_weekend_blindbox` `months_lookback` 无校验，已加正整数 + ≤ MAX_LOOKBACK_DAYS/30 双重检查。
- `tesla_charging_by_location` 接受 `days=-1` 静默当成"全部时间"。已改为 `if days and days > 0:`。
- smoke test 阶段额外捕获：`tesla_drives(days=None)` 在 line 1928 `actual_days < days * 0.9` 仍崩 NoneType；`get_vehicle_persona_status(days_lookback=None)` 在校验入口 `None <= 0` 崩 TypeError。两处均已加 `is not None` 守卫。

**数据正确性（2 项）**

- `tesla_savings` 月度"估算能耗"实际用了 lifetime 全表（fallback SQL 无 `start_date` 谓词）。已加 `month_start_utc` 边界，月度查询只覆盖当月。
- `get_charging_vintage_data` 在删除 `cp.outside_temp_avg` 后温度字段永远 None（已被 LATERAL JOIN 修复补偿回来）。

**🔴 高严重性能 / 架构（4 项，B1–B4）**

- **B1 event-loop 阻塞**：38 个 async 工具直接调同步 psycopg2，HTTP 模式下并发全部串行。已加 `_query_async` / `_query_one_async` / `_cached_*_async` 4 个 async wrapper（内部 `asyncio.to_thread`），并把 64 处 async 函数内的同步 DB 调用转 async。
- **B2 cache stampede**：`_cached_result` 冷键 N 并发全部跑同一个重查询。已加 `_result_inflight: dict[str, asyncio.Future]`，第一个 misser 跑 `fn()`，其余 await 同一个 future。
- **B3 配置缺失静默归零**：`TESLA_CAR_PARAMS` 未设时 `kwh_per_km=0`，所有能耗静默变成 0。已加 `_check_car_config` helper，9 个能耗类工具入口检查并返回友好 ⚠️ 错误。
- **B4 3 工具无 days 校验**：见上。

**🟡 中严重（5 项，B5–B11）**

- **B5 QWeather 锁跨 loop**：`_qw_locid_flight_lock` 缓存的 `asyncio.Lock` 绑定第一次事件循环，新 loop 触发 `RuntimeError`。已改为 `(loop_id, lock)` tuple 并 `asyncio.get_running_loop()` 检查。
- **B6 QWeather 驱逐**：所有 in-flight 锁都占用时旧代码跳过驱逐、插入第 N+1 个键。已加 phase-2 force-evict 最旧键。
- **B7 坏连接放回 pool**：异常路径 `_pool.putconn(conn)` 把半坏连接放回 pool，导致下一个 8 个 caller 全失败。已加 `_put_conn_safe`：检测 `conn.closed`，坏连接 `putconn(close=True)`。
- **B8 连接池耗尽**：第 9 个并发直接裸 `PoolError`。`_get_conn` 加 retry loop（默认 2s / 50ms 步长），超时后抛友好 `RuntimeError("Database connection pool exhausted ...")`。
- **B9 cache version 隔离**：升级时缓存返回旧格式。已加 `_vkey(*parts) = f"v{__version__}:..."`，12 处 cache key 全部改名。升 v1.2.3→v1.2.4 时旧 key 前缀失配自动失效。
- **B11 narrative 无 LIMIT**：`generate_travel_narrative_context` 多年窗口一次返回所有 drives。已加 `LIMIT_NARRATIVE` (默认 500) + 窗口 ≤ `MAX_LOOKBACK_DAYS` 双重保护，capped 时响应带 `"Timeline truncated"` 警告。

**🟢 资源 / 死代码（4 项，B10、B12–B15）**

- **B10 ROUTINE_CACHE 泄漏**：每 car_id 只增不删。已加 `_routine_cache_prune` + `ROUTINE_CACHE_MAX=256` FIFO 上限。
- **B12** 见"时区与单位"。
- **B13** `check_driving_achievements` midnight-ghost 查了 `outside_temp_avg` / `end_address_id` 但消费者从未用。已删。
- **B14** `get_longest_trip_on_single_charge` 的 `LEAD(cp.end_date) AS next_charge_end` 算但从未引用。已删。
- **B15** `tesla_live` 单独跑一次 `SELECT state FROM states` 多余 round-trip。已合并到主查询的 `LEFT JOIN LATERAL`。

#### 测试

- `test_all.py` 新增 **21 条 REGRESSION-v1.2.4 断言**，加上 smoke test **80/80 全绿**。

#### 配置

- 新增 `TESLA_DB_POOL_RETRY_WINDOW_SEC`（默认 2.0）+ `TESLA_DB_POOL_RETRY_SLEEP_SEC`（默认 0.05）+ `TESLA_LIMIT_NARRATIVE`（默认 500）+ `TESLA_ROUTINE_CACHE_MAX`（默认 256）。全部向后兼容。

#### 备注

- **数据库访问仍然 100% 只读**。本版本共修改 ~743 行代码 + 新增 ~237 行测试代码，0 处 INSERT/UPDATE/DELETE/CREATE/ALTER/DROP/commit/rollback。

---

### English

Stability & correctness patch release — **0 database changes**. Fixes **22 bugs** spanning SQL schema errors, timezone mis-bucketing, silent crashes on None/negative inputs, HTTP-mode performance issues, and cache safety. Every fix is a read-only SELECT text optimization or Python logic improvement — deployable via `git pull` with no migration or downtime.

#### Bug fixes

**SQL schema errors (2)**

- `tesla_monthly_report` / `tesla_monthly_summary` referenced `d.battery_level` in the second `UNION ALL` branch of the `events` CTE — the `drives` table has no such column, causing `column does not exist` at runtime. Replaced with `p.battery_level` (after JOIN positions).
- `get_charging_vintage_data` referenced `cp.outside_temp_avg` — `charging_processes` has no such column (it lives on `drives`). Removed the column from the SELECT, then added `LEFT JOIN LATERAL positions` to recover the temperature reading (latest non-null `outside_temp` ≤ `cp.start_date`).

**Timezone & units (3)**

- `tesla_monthly_report` month boundaries used naive `datetime(year, month, 1)`, shifting the window by ±14h for non-UTC users (`Asia/Shanghai`, etc.). Replaced with `datetime(..., tzinfo=USER_TZ).astimezone(timezone.utc)` to match sibling tools.
- `tesla_monthly_summary`'s `date_trunc('month', start_date)` depended on the Postgres session timezone. Replaced with `date_trunc('month', start_date AT TIME ZONE 'UTC' AT TIME ZONE %s)` and bound `USER_TZ`.
- `tesla_weather` displayed `None°C` / `None°F` when QWeather omits `temp`/`feelsLike`. Added `if temp_c is not None` guard.

**Input validation & crashes (5)**

- 9 tools crashed with `TypeError: timedelta(days=None)` on `days=None`. Added `_cutoff_from_days(None)` helper that falls back to `MAX_LOOKBACK_DAYS`.
- `calculate_eco_savings_vs_icev`, `check_driving_achievements` had no `days` validation. Added `_validate_days`.
- `generate_weekend_blindbox` `months_lookback` was unbounded. Added positive-integer + ≤ MAX_LOOKBACK_DAYS/30 checks.
- `tesla_charging_by_location` silently accepted `days=-1` as "all time". Changed to `if days and days > 0:`.
- Smoke test caught two more downstream issues: `tesla_drives(days=None)` crashed at `actual_days < days * 0.9`; `get_vehicle_persona_status(days_lookback=None)` crashed at the `None <= 0` validation entry. Both fixed with `is not None` guards.

**Data correctness (2)**

- `tesla_savings` monthly fallback estimate was actually a lifetime scan (no `start_date` predicate). Added `month_start_utc` boundary.
- `get_charging_vintage_data` would have permanently lost temperature after the column removal — recovered via LATERAL JOIN.

**🔴 High severity (4, B1–B4)**

- **B1 event-loop blocking**: 38 async tools called sync psycopg2 directly. Added `_query_async` / `_query_one_async` / `_cached_*_async` wrappers using `asyncio.to_thread`; converted 64 sync DB call sites inside async functions.
- **B2 cache stampede**: `_cached_result` allowed N concurrent cold callers to all run the expensive aggregate. Added `_result_inflight: dict[str, asyncio.Future]` — first misser runs `fn()`, others await the same future.
- **B3 silent zero energy**: Missing `TESLA_CAR_PARAMS` made `kwh_per_km=0` propagate silently. Added `_check_car_config` guard on 9 energy tools returning a friendly ⚠️ error.
- **B4 three tools without days validation**: see above.

**🟡 Medium severity (6, B5–B11)**

- **B5 QWeather lock cross-loop**: cached `asyncio.Lock` bound to first event loop. Switched to `(loop_id, lock)` tuple with `asyncio.get_running_loop()` check.
- **B6 QWeather eviction**: when all in-flight locks held, old code skipped eviction and inserted the N+1th key. Added phase-2 force-evict of oldest.
- **B7 broken connection returned to pool**: exception path put half-dead connections back, poisoning the next 8 callers. Added `_put_conn_safe` that detects `conn.closed` and `putconn(close=True)`.
- **B8 pool exhaustion**: 9th concurrent caller hit raw `PoolError`. `_get_conn` now retries briefly (default 2s / 50ms) before raising a friendly `RuntimeError("Database connection pool exhausted ...")`.
- **B9 cache version isolation**: upgrades returned stale format. Added `_vkey(*parts) = f"v{__version__}:..."`; renamed all 12 cache key sites. Old `v1.2.3:` keys no longer match on v1.2.4 startup.
- **B10 ROUTINE_CACHE leak**: per-car_id unbounded dict. Added `_routine_cache_prune` + `ROUTINE_CACHE_MAX=256` FIFO cap.
- **B11 narrative unbounded**: `generate_travel_narrative_context` could pull all drives in a multi-year window. Added `LIMIT_NARRATIVE` (default 500) + ≤ `MAX_LOOKBACK_DAYS` window cap, with `"Timeline truncated"` warning.

**🟢 Cleanup (3, B12–B15)**

- **B12** see Timezone & units.
- **B13** `check_driving_achievements` midnight-ghost query selected `outside_temp_avg` / `end_address_id` it never read.
- **B14** `get_longest_trip_on_single_charge` computed `LEAD(cp.end_date) AS next_charge_end` that was never referenced.
- **B15** `tesla_live` ran a separate `SELECT state FROM states` round-trip; folded into the main query via `LEFT JOIN LATERAL`.

#### Testing

- `test_all.py` adds **21 new REGRESSION-v1.2.4 assertions**; comprehensive smoke test reports **80/80 passing**.

#### Configuration

- New envs: `TESLA_DB_POOL_RETRY_WINDOW_SEC` (default 2.0), `TESLA_DB_POOL_RETRY_SLEEP_SEC` (default 0.05), `TESLA_LIMIT_NARRATIVE` (default 500), `TESLA_ROUTINE_CACHE_MAX` (default 256). All backward-compatible.

#### Notes

- **Database access remains 100% read-only.** ~743 lines changed in `tesla.py`, ~237 lines added in `test_all.py`. Zero `INSERT`/`UPDATE`/`DELETE`/`CREATE`/`ALTER`/`DROP`/`commit`/`rollback` introduced.

---

## [1.2.3] - 2026-07-03

### 中文

能耗分类大版本 —— **0 项数据库改动**。把原本纠缠在一起的功耗指标拆分成**三种独立类别**（行驶 / 充电 / 停车），各自从原始数据源独立计算、并列展示、永不混入运算。同时新增 **露营模式** 检测。

#### 新增

- **`tesla_vampire_drain` 露营模式标记（rate-based）** —— 停车时间 **> 8 小时** 且该段停车的**平均每小时耗电速率** ≥ `TESLA_CAMPING_KWH_PER_HOUR`（默认 **0.8 kWh/h**）的事件自动标记为 `🏕️ 露营模式`。kWh 换算使用**固定 75 kWh 参考电池** —— 实际电池是 75 / 82 / 100 kWh 都不影响判定。哨兵 / 第三方 app 操作**不单独区分**，只看速率。所有露营事件**保证附带停车点天气**，根因一眼可见。
- **`tesla_monthly_summary` 三列分立** —— 新增 `Drive kWh`（行驶，续航差值估算）/ `Charge kWh`（充电，会话汇总）/ `Vampire kWh`（停车，事件表聚合）三列独立展示。`Wh/km` **只用行驶 kWh**，不再被充电损耗和停车耗电污染。
- **`tesla_monthly_report` 三种能量分开** —— 行驶 / 充电 / 停车耗电各自一行，与上月对比也按类别分别给出 delta。

#### 变更

- `tesla_efficiency` 周报标签改清楚 —— `估算 X kWh` → `行驶 X kWh`，`实际充电 Y kWh` → `充电 Y kWh`，顶部加注 "Two independent metrics — never mixed"。
- `tesla_vampire_drain` 文档说明露营模式行为以及天气保证。
- `tesla_trip_cost` 继续 v1.2.3 行为：天气只在输出末尾 `🌦️ Current weather` 段呈现，**绝不参与 cost 公式**。

#### Bug 修复

- `tesla_vampire_drain` 多事件路径下 `dict.fromkeys(...)` 抛 `TypeError: unhashable type: \'dict\'` —— 改为基于 `id(r)` 的显式去重，保留首次出现顺序。

#### 测试

- `test_all.py` **114 通过 / 0 失败**（was 92）。新增 12 个露营模式用例（含边界：阈值恰好相等 0.8 kWh/h、刚低于阈值 0.75、长时间低速率、电池大小无关验证）+ 7 个三类分立用例 + 2 个 `dict.fromkeys` 回归用例。

#### 配置

- 新增 `TESLA_CAMPING_KWH_PER_HOUR`（默认 `0.8 kWh/h`；设 ≤ 0 关闭）。kWh 换算用**固定 75 kWh 参考电池**，与实际电池大小无关。现有 `TESLA_VAMPIRE_WEATHER_MAX` 现在也覆盖露营事件。

#### 备注

- 数据库访问**仍然只读**。三种 kWh 全部由现有 `drives` / `charging_processes` / `positions` 表通过 `LEAD()` 事件 CTE 聚合 —— 无 schema 变更、无写入。

#### 配置（v1.2.3 后续微调，仍属同一发布）

- **车配置强制环境变量化** —— 删除模块级 `BATTERY_KWH=75` / `BATTERY_RANGE_KM=525` / `KWH_PER_KM` 硬编码常量。Car info 现在**完全从环境变量读取**（`TESLA_CAR_PARAMS` 优先，回退 `TESLA_BATTERY_KWH + TESLA_BATTERY_RANGE_KM`）。如果都没设，启动时打 **WARNING** 并用占位值（kwh=0, range_km=1）让电量估算出 0，**显眼地错**而不是悄悄错（避免 Model 3P / Model YL 真实容量被默认值污染）。
- **`TESLA_CAMPING_KWH_PER_HOUR` 默认值 0.8 kWh/h** —— 露营模式用 rate-based 判定：drain% × 固定 75 kWh 参考 / hours_parked ≥ 0.8。电池大小无关。
- **Docker workflow `latest` 标签** —— `docker.yml` 新增 `type=raw,value=latest`，每次 `v*` tag 触发构建都会同步打 `latest`，镜像 `ghcr.io/6547709/teslamate-mcp:latest` 当前指向 v1.2.3。

---

### English

Energy-categorisation release — **0 database changes**. Splits the previously entangled power-consumption metric into **three independent categories** so each is computed from its primary source, displayed side-by-side, and never mixed in calculations. Also adds a "camping mode" detector on vampire drain.

#### Added

- **Camping mode flag in `tesla_vampire_drain`** (rate-based) — parked periods with parking time **> 8 hours** AND **average drain rate** ≥ `TESLA_CAMPING_KWH_PER_HOUR` (default **0.8 kWh/h**) are tagged `🏕️ 露营模式`. The kWh conversion uses a **fixed 75 kWh reference battery** — the threshold is the same whether the actual car is 75 / 82 / 100 kWh. Sentry / third-party-app activity is **not distinguished** from camping use — only the drain rate matters. Camping events always receive parking-location weather regardless of drain rank, so the cause is visible at a glance.
- **Three independent kWh columns in `tesla_monthly_summary`** — `Drive kWh` (range-drop estimate), `Charge kWh` (sessions), `Vampire kWh` (parked drain), each aggregated from its primary table. `Wh/km` now uses **driving kWh only** and is never contaminated by charging losses or vampire drain.
- **Three energy lines in `tesla_monthly_report`** — Driving / Charging / Vampire energy each on its own line, with per-category prev-month delta in the comparison line.

#### Changed

- `tesla_efficiency` weekly output relabels `估算 X kWh` → `行驶 X kWh` and `实际充电 Y kWh` → `充电 Y kWh`, with top-of-output note "Two independent metrics — never mixed".
- `tesla_vampire_drain` docstring updated to describe camping-mode behaviour and the parking-weather guarantee for camping events.
- `tesla_trip_cost` retains the v1.2.3 behaviour: weather shown only at the end as a `🌦️ Current weather` block; **never participates in the cost formula**.

#### Bug fixes

- `tesla_vampire_drain` weather-fetch targets list crashed with `TypeError: unhashable type: \'dict\'` when more than one event qualified (top-N or camping). Replaced `dict.fromkeys(...)` (which hashes by value) with explicit `id(r)`-keyed dedup, keeping first-seen order.

#### Testing

- `test_all.py` **114 passed / 0 failed** (was 92). New coverage: 12 camping-mode tests (incl. edge cases: exactly-at-threshold 0.8 kWh/h, just-below 0.75, long-park low-rate, battery-size-independence), 7 three-category separation tests, 2 `dict.fromkeys` regression tests.

#### Configuration

- New env var: `TESLA_CAMPING_KWH_PER_HOUR` (default `0.8 kWh/h`; set ≤ 0 to disable). The kWh conversion uses a **fixed 75 kWh reference battery** — battery-size-independent. Existing `TESLA_VAMPIRE_WEATHER_MAX` now also covers camping events.

#### Notes

- Database access remains strictly read-only. All three categories are computed from existing `drives` / `charging_processes` / `positions` tables via a `LEAD()`-based events CTE — no schema changes, no writes.

#### Configuration refinements (still v1.2.3, same release)

- **Car config is now strictly env-driven** — removed module-level `BATTERY_KWH=75` / `BATTERY_RANGE_KM=525` / `KWH_PER_KM` hardcoded constants. Car info MUST come from the environment (`TESLA_CAR_PARAMS` preferred, falling back to `TESLA_BATTERY_KWH + TESLA_BATTERY_RANGE_KM`). If neither is set, a WARNING is logged at startup and placeholder values (`kwh=0`, `range_km=1`) are used so energy estimates come out to zero — loudly wrong instead of silently wrong (no more 75 kWh pollution on Model 3P / Model YL).
- **`TESLA_CAMPING_KWH_PER_HOUR` default 0.8 kWh/h** — camping-mode judgment uses a rate-based threshold: `drain% × fixed 75 kWh reference / hours_parked ≥ 0.8`. Battery-size-independent by design.
- **Docker workflow now tags `latest`** — added `type=raw,value=latest` to `docker.yml`. Every `v*` tag build now also publishes `:latest`, so `ghcr.io/6547709/teslamate-mcp:latest` currently points to v1.2.3.
---

## [1.2.2] - 2026-07-03

Patch release — **0 database changes**. Eliminates redundant (billed) QWeather GeoAPI calls under concurrency. Purely an in-app reliability/cost fix; no API surface, tool count, or behaviour changes for callers.

### Fixed

- **QWeather LocationID single-flight (P0-2)** — `_qweather_locationid()`
  previously released its lock between the cache-miss check and the cache
  write, so multiple coroutines resolving the **same** grid cell concurrently
  could each fire a separate (billed) GeoAPI `city/lookup` request. Added a
  per-grid-key `asyncio.Lock` so only the first caller performs the lookup; the
  rest await it and reuse the cached result (double-checked after acquiring the
  flight lock). Directly reduces GeoAPI spend under concurrent access. The
  in-flight lock map is itself guarded by the existing threading lock and
  bounded (free locks pruned past `_QW_INFLIGHT_MAX = 256`).

### Testing

- Added a **Layer 5** regression test to `test_all.py`: 20 concurrent lookups
  of the same grid cell now make exactly **1** GeoAPI call (was up to 20);
  cache hits make 0; a different cell makes exactly 1 more. **92 passed / 0
  failed** overall (88 → 92).

---

## [1.2.1] - 2026-06-30

Weather integration release — **0 database changes**. Adds optional weather enrichment via QWeather (和风天气): a real-time weather tool, a weather-bucketed efficiency analysis backed by QWeather's *historical* API, and a destination-weather correction for trip-cost estimates. Fully backward compatible: when `QWEATHER_API_KEY` / `QWEATHER_API_HOST` are unset, all weather features are silently disabled and nothing else changes.

### Added

- **`tesla_weather`** — current weather (temperature, feels-like, humidity,
  wind, precipitation, visibility, conditions) at the vehicle's latest GPS
  position. Complements TeslaMate's single `outside_temp` sensor reading.
- **`tesla_efficiency_by_weather`** — efficiency grouped by actual weather
  condition (clear/cloudy/rain/snow/fog/wind), not just temperature. Back-fills
  each drive's weather from QWeather's historical API using the drive's midpoint
  coordinate + date, then aggregates kWh/distance per condition and shows the
  delta vs clear weather. Samples the most recent drives (default 60, via
  `TESLA_WEATHER_SAMPLE_MAX`) to stay within API limits; result cached 6h.
- **`tesla_trip_cost` weather correction** — when QWeather is configured, the
  destination's current weather applies an energy multiplier to the estimate
  (rain +15%, snow +30%, fog +10%, wind +12%; clear/cloudy unchanged).
- New env vars: `QWEATHER_API_KEY`, `QWEATHER_API_HOST` (dedicated host, e.g.
  `xxxx.re.qweatherapi.com`), `TESLA_QWEATHER_TIMEOUT` (default 8s),
  `TESLA_WEATHER_SAMPLE_MAX` (default 60).

### Technical notes

- **Dedicated API host** — QWeather (2024+) rejects the legacy public
  `devapi/api.qweather.com` hosts with `403 Invalid Host`; each account now has
  a private `*.re.qweatherapi.com` host. `QWEATHER_API_HOST` accepts a value
  with or without scheme/trailing slash and is normalised to a bare host.
- **Coordinates vs LocationID** — realtime weather accepts raw WGS-84 `lon,lat`
  directly; historical weather requires a QWeather LocationID, so coordinates
  are resolved to the nearest LocationID via GeoAPI (grid-snapped ~5km cache to
  minimise calls).
- **Historical condition bucketing** — the daily summary has no condition text,
  so the bucket is derived from the most-severe hourly sample (with a
  precipitation fallback ⇒ rain).
- **Graceful degradation** — every weather helper returns `None` on disabled /
  network / parse / API error, and the new tools return a friendly hint, so
  existing deployments are completely unaffected.

### Testing

- `test_all.py`: weather classification (incl. case-insensitive English and
  snow-before-rain precedence), disabled-path returns, host normalisation, and
  energy-factor table. All tools still smoke-tested.

## [1.2.0] - 2026-06-30

Geocoding accuracy release — **0 database changes**. Adds optional AMAP (高德地图) as a higher-priority geocoding source for Chinese addresses, with built-in GCJ-02 → WGS-84 coordinate conversion. Fully backward compatible: when `AMAP_API_KEY` is unset the behaviour is identical to before (Nominatim only).

### Added

- **AMAP (高德) geocoding** for `tesla_trip_cost`. New fallback chain after the
  local addresses table and file cache: **AMAP → Nominatim**. AMAP gives far
  better accuracy for Chinese place names (e.g. "腾讯滨海大厦", "万达广场").
- **`gcj02_to_wgs84()` coordinate conversion** (community-standard transform,
  ~1-2 m accuracy). AMAP returns GCJ-02 ("Mars") coordinates while TeslaMate
  stores WGS-84; every AMAP result is converted back to WGS-84 before caching
  and distance math, eliminating the 50-500 m systematic offset.
- New env vars: `AMAP_API_KEY` (enable AMAP), `TESLA_AMAP_TIMEOUT` (default 8s).

### Notes

- **Graceful degradation**: no key, network error, rate limit, or no-match →
  `_amap_geocode()` returns `None` and the tool transparently falls back to
  Nominatim. Existing deployments are unaffected.
- **Coordinate safety**: outside mainland China GCJ-02 == WGS-84, so the
  transform is a no-op there (verified for US coordinates).
- AMAP results share the existing bounded persistent geocode cache (LRU,
  default 1000 entries), so repeat lookups stay free.

## [1.1.1] - 2026-06-26

Application-layer hardening & performance release — **0 database changes**. Fixes one cross-tool inconsistency bug, adds input validation, bounded caches, and pushes trip classification into SQL. All 36 tools validated by a new no-database test harness (57/57 assertions passed).

### Fixed
- **Vampire-drain threshold inconsistency (BUG-4)** — the standalone `tesla_vampire_drain` tool used an 8-hour parked threshold while `generate_monthly_driving_report` and `get_vehicle_persona_status` used 3 hours, producing contradictory results across tools. Unified all three behind shared constants `VAMPIRE_MIN_HOURS` (8) / `VAMPIRE_MAX_HOURS` (168), overridable via `TESLA_VAMPIRE_MIN_HOURS` / `TESLA_VAMPIRE_MAX_HOURS`.

### Added
- **`_validate_days()` helper** — centralized look-back validation (rejects negative / zero / oversized `days`; cap `TESLA_MAX_LOOKBACK_DAYS`, default 3650). Wired into 10 date-range tools plus `n` / `month` / `start_month` / `end_month` checks in `tesla_driving_score`.
- **`test_all.py`** — full functional test harness that runs with **no live database** (monkeypatches `_query` / `_query_one` with a fake-DB layer). Three layers: fix-point unit tests, smoke-call of every `@mcp.tool()`, and error-path validation. 57/57 passed.

### Changed
- **`tesla_trips_by_category` (PERF-4)** — `shopping` / `leisure` classification now pre-filters address names in SQL via `ILIKE ANY(ARRAY[...])`, shrinking the candidate set from a potential full-table scan to keyword-matching rows only (Python still re-checks precedence). Read-only; no schema change.
- **`_classify_trip` (PERF-1)** — shopping / leisure keyword lists hoisted to module-level pre-lowercased tuples instead of being rebuilt and re-lowercased on every call (invoked thousands of times inside `tesla_trip_categories`).
- **In-memory caches (PERF-2)** — `_cache` / `_result_cache` now carry a per-entry TTL and run lazy garbage-collection via `_prune_cache()`, capped at `TESLA_CACHE_MAX_ENTRIES` (default 500), preventing unbounded growth in long-running HTTP-mode servers.
- **`tesla_trip_cost` (ISSUE-3)** — rejects too-short/ambiguous queries (`< 2` chars) with a clear message, and ranks local-address candidates by **actual visit frequency** (from `drives.end_address_id`) so the most-relevant place wins instead of arbitrary `id DESC`.
- **`_find_nearby_geofence` (ISSUE-2)** — planar geofence distance now multiplies the longitude delta by `cos(latitude)`, removing the ~18% longitude-axis looseness at mid/high latitudes.
- **Persistent geocode cache (ISSUE-4)** — `~/.cache/teslamate-mcp/geocode.json` is now bounded at `TESLA_GEOCODE_CACHE_MAX` entries (default 1000) with FIFO/LRU eviction, so repeated misses can no longer grow the file without bound.
- **`tesla_status` charging detection (ISSUE-5)** — open-session window widened 24h → 48h and now also honours live vehicle `state = 'charging'`, so very long destination AC charges are no longer misreported as "not charging".

### Performance
- `_classify_trip` hot loop: ~30–40% less string work per call (no per-call list build / `.lower()`).
- `tesla_trips_by_category(shopping|leisure)`: candidate rows scanned cut from up to 2000 (multi-batch) to keyword-matched rows in a single query.
- Memory: in-process caches now bounded; no steady-state growth under sustained HTTP traffic.

### Breaking Changes
- None. All tool signatures and return formats remain backwards-compatible with v1.1.0.

[1.1.1]: https://github.com/6547709/teslamate-mcp/releases/tag/v1.1.1

## [1.1.0] - 2026-04-22

Performance & observability release — **0 database changes**, pure in-app optimizations. Cold-cache workload reduced by 28%, warm-cache by 69%. New diagnostic tool. 36/36 tools validated.

### Added
- **`tesla_version()` tool** — first tool in the catalog, returns server version, tool count, Python / fastmcp / psycopg2-binary versions, timezone, units, and live TeslaMate DB health check. Use this to confirm deployment identity and connectivity.
- **FastMCP metadata** — server now advertises `name=teslamate-mcp`, `version`, `instructions`, and `website_url` during MCP handshake (visible to any compliant client without a tool call).
- **`__version__` constant** with multi-level resolution: `VERSION` env var (Docker build-arg) → hardcoded `__version__` → `git describe` → `"dev"`.
- **Persistent Nominatim geocode cache** — `~/.cache/teslamate-mcp/geocode.json`, cross-process and thread-safe.
- **Result-level cache framework** (`_cached_result`) — wraps entire tool output with per-key TTL.
- **`PERFORMANCE_REVIEW.md`**, **`PERFORMANCE_IMPLEMENTATION.md`**, **`TEST_REPORT.md`** committed to repo for transparency.

### Changed
- **`tesla_savings`**: 4 independent queries → **2 queries** via `FILTER (WHERE ...)` aggregate condition. Cold 200ms → 8ms (27×).
- **`tesla_monthly_report`**: 4 queries → **2 queries** via `FILTER`. Cold 300ms → 5ms (60×). Historical months cached 1 day; current month always live.
- **`tesla_trip_cost`**: 3-stage fallback — first search local TeslaMate `addresses` table (1,700+ visited places), then persistent file cache, finally Nominatim. Local hits drop cold latency from 1296ms to ~15ms (86×).
- **`tesla_battery_health`** / **`tesla_efficiency_by_temp`** / **`tesla_charging_by_location`** / **`tesla_top_destinations`**: added result-level caching (1h / 30min / 30min / 30min). Warm hits drop to microseconds.
- **`LIMIT_DRIVES`** default **500 → 1000**; **`LIMIT_TRIP_CATEGORIES`** default **500 → 1000**. `tesla_drives(365+)` now covers 247 days of history instead of 131 (+88%). Override via `TESLA_LIMIT_DRIVES` / `TESLA_LIMIT_TRIP_CATEGORIES` envs.
- **`tesla_drives` header** now displays the actual data window when the requested `days` exceeds available data (e.g. `days=10000` shows `2025-08-17 → 2026-04-20, 247 days of data, 1000 trips` instead of a misleading "last 10000 days").

### Fixed
- **Bug: `tesla_trip_cost("")` false match** — empty/whitespace destination no longer matches arbitrary addresses via `ILIKE '%%'`. Input is now validated with a clear error message.

### Performance
- Full suite benchmark (36 tools, live database):
  - v1.0.0: 4400 ms · avg 126 ms/call
  - v1.1.0 cold cache: **3168 ms** · avg 90 ms/call (↓ 28%)
  - v1.1.0 warm cache: **1369 ms** · avg 39 ms/call (↓ 69%)
- Cache hit speed-ups: `tesla_battery_health` 8827× · `tesla_top_destinations` 1612× · `tesla_charging_by_location` 125× · `tesla_savings` 99× · `tesla_efficiency_by_temp` 69× · `tesla_monthly_report` 31×
- **6/6** cached tools verified deterministic (hash cold == warm == 3rd call).
- **15/15** edge-case inputs handled gracefully (zero crashes).

### Breaking Changes
- None. All tool signatures and return formats are backwards-compatible with v1.0.0.

[1.1.0]: https://github.com/6547709/teslamate-mcp/releases/tag/v1.1.0

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
