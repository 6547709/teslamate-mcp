# tesla.py 性能审计报告

> 审计对象：`tesla.py` v1.0.0（4220 行，35 个 MCP 工具）
> 审计数据：真实 TeslaMate PG 18.3（positions 18.6M 行 · 2.39 GB，drives 5.6k 行 · 1.8 MB）
> 审计基线：35/35 工具全通过，累计 4.4s，平均 126 ms/次
> 审计时间：2026-04-21 22:35

---

## 🎯 执行摘要（TL;DR）

### 值得优化的 Top 5 瓶颈

| # | 工具 | 实测延迟 | 根因 | 修复成本 | 预期收益 |
|---|---|---|---|---|---|
| 1 | **`tesla_battery_health`** | 1588 ms | 18.6M 行 positions 全表 GROUP BY month，现有 partial index 缺 `battery_level` 列 | 🟡 中（加索引） | **10-50×** → <50 ms |
| 2 | **`tesla_trip_cost`** | 1296 ms | Nominatim 外部 HTTP 占 800-1000 ms（不可控） | 🟢 低（加本地缓存） | 重复目的地 **∞×** → <10 ms |
| 3 | **`tesla_tpms_history`** | 未测 | 扫 18.6M positions 按 4h 桶聚合，无 tpms 列索引 | 🟡 中（加索引） | **3-10×** |
| 4 | **`tesla_savings`** | ~200 ms | 4 次独立查询可合并为 2 次 | 🟢 低 | **2×**（RTT 减半） |
| 5 | **`tesla_monthly_report`** | ~300 ms | 4 次独立查询可合并为 2 次 | 🟢 低 | **2×** |

### 投入产出比建议

**"周末下午就能做完"档**（总投入 ~2 小时，覆盖 80% 收益）：
- ✅ **A-1**：加 3 个索引（battery_health / tpms_history / positions 复合）
- ✅ **A-2**：给 Nominatim 加本地文件缓存（`~/.cache/teslamate-mcp/geocode.json`）
- ✅ **A-3**：`tesla_savings` 和 `tesla_monthly_report` 用 `FILTER (WHERE)` 合并查询

**"锦上添花"档**（总投入 ~1 天）：
- B-1：给 `positions` 热点字段加 `_cached_query` 缓存（TTL 60s）
- B-2：连接池参数根据并发场景调优（`maxconn=8` 可能不够）

**"暂不建议做"**：
- ❌ 用 async DB 驱动（asyncpg）—— 收益小、改动大、psycopg2 成熟度更好
- ❌ 引入 Redis 缓存 —— 单人使用场景杀鸡用牛刀

---

## 一、数据库层

### 1.1 表规模现状（关键基线）

| 表 | 行数 | 大小 | 评级 |
|---|---|---|---|
| `positions` | **18,613,543** | **2.39 GB** | ⚠️ 唯一大表，所有性能问题源头 |
| `charges` | 565,762 | 102 MB | 较大，但默认只查 join 用 |
| `drives` | 5,606 | 1.8 MB | 小到可以全表扫 |
| `charging_processes` | 903 | 296 KB | 迷你 |
| `addresses` / `geofences` / `cars` | <1k 各 | ~KB | 迷你 |

**关键结论**：所有真正慢的查询，根源都在 `positions` 这张 18.6M 行 / 2.39 GB 的大表上。其他表都小到可以忽略索引问题。

### 1.2 现有索引分析

`positions` 表（重点关注）：

```
positions_pkey                                                 (id) UNIQUE
positions_car_id_index                                         (car_id)
positions_date_index                                           (date) BRIN
positions_drive_id_date_index                                  (drive_id, date) BRIN
positions_car_id_date__ideal_battery_range_km_IS_NOT_NULL_idx  (car_id, date, (range IS NOT NULL)) WHERE range IS NOT NULL  ← partial
```

**观察**：
- ✅ `car_id` 有 B-Tree 索引，单车过滤快
- ✅ `date` 有 BRIN 索引（时间序列表的正确选择，空间省）
- ✅ 有针对 `ideal_battery_range_km` 的 partial index
- ❌ **没有任何针对 `tpms_pressure_*` 的索引**
- ❌ **没有针对 `battery_level = 100` 的针对性索引**（battery_health 用的就是这个条件）

### 1.3 建议新增的索引（⚡ 收益最高）

#### 索引 A：battery_health 专用

**问题查询**（`tesla_battery_health` 第 1492 行）：

```sql
SELECT date_trunc('month', date), AVG(ideal_battery_range_km), COUNT(*)
FROM positions
WHERE car_id = %s
  AND battery_level = 100
  AND ideal_battery_range_km IS NOT NULL
GROUP BY date_trunc('month', date)
ORDER BY month DESC
```

**当前现象**：1588 ms。执行计划大概率是"扫 partial index → Filter battery_level=100 → GROUP BY"，因为索引不含 `battery_level`。

**建议索引**：

```sql
CREATE INDEX CONCURRENTLY idx_positions_battery_full
ON positions (car_id, date)
WHERE battery_level = 100 AND ideal_battery_range_km IS NOT NULL;
```

满电时刻的 position 在总体数据里只占极小比例（<1%），partial index 体积小、命中快。预期降到 **20-50 ms**。

#### 索引 B：tpms_history 专用

**问题查询**（`tesla_tpms_history` 附近，约第 2751 行）：查 4h 桶聚合胎压，覆盖全时段 `positions` 大表。

**建议索引**（BRIN 更省空间）：

```sql
CREATE INDEX CONCURRENTLY idx_positions_tpms_car_date_brin
ON positions USING BRIN (car_id, date)
WHERE tpms_pressure_fl IS NOT NULL;
```

或如果 TPMS 查询非常频繁：

```sql
CREATE INDEX CONCURRENTLY idx_positions_tpms_car_date_btree
ON positions (car_id, date)
WHERE tpms_pressure_fl IS NOT NULL;
```

#### 索引 C：state_history 用的 `usable_battery_level`（次要）

如果 `tesla_state_history` 经常被叫，`positions.usable_battery_level` 列值得观察一下。**建议先 EXPLAIN ANALYZE 跑一下该工具，再决定要不要加。**

### 1.4 索引应用建议

- 三个索引全用 `CONCURRENTLY` —— 不锁表、不影响 TeslaMate 正常写入
- 需要在 **TeslaMate 数据库上** 跑一次（不是 MCP 服务上），**建议由你本人在 DB 服务器上执行**
- 我可以生成一个 `tools/add_indexes.sql` 脚本，包含三条 `CREATE INDEX` + 回滚语句

---

## 二、SQL 结构优化（合并多次查询）

### 2.1 发现：代码里 **0 处用 `FILTER (WHERE)`**

这是 PostgreSQL 9.4+ 的聚合条件语法，完美适合"同一个表不同条件聚合"场景。当前代码有至少 3 个工具可以用它大幅减少 round-trip。

### 2.2 案例 1：`tesla_savings` 4 → 1 查询

**当前**（第 2002-2023 行，4 次独立 query）：

```python
lifetime_drive  = _query_one("SELECT SUM(distance) FROM drives WHERE car_id = %s AND distance > 0", ...)
lifetime_charge = _query_one("SELECT SUM(charge_energy_added) FROM charging_processes WHERE car_id = %s AND end_date IS NOT NULL", ...)
monthly_drive   = _query_one("... AND date_trunc('month', start_date) = date_trunc('month', NOW())", ...)
monthly_charge  = _query_one("... AND date_trunc('month', start_date) = date_trunc('month', NOW())", ...)
```

**优化后**（合并为 2 次，可进一步合并为 1 次用 CTE）：

```sql
-- drives（1 次查出两组）
SELECT
    COALESCE(SUM(distance), 0)                                                        AS lifetime_km,
    COALESCE(SUM(distance) FILTER (WHERE start_date >= date_trunc('month', NOW())), 0) AS monthly_km
FROM drives
WHERE car_id = %s AND distance > 0;

-- charging_processes（1 次查出两组）
SELECT
    COALESCE(SUM(charge_energy_added), 0)                                                          AS lifetime_kwh,
    COALESCE(SUM(charge_energy_added) FILTER (WHERE start_date >= date_trunc('month', NOW())), 0) AS monthly_kwh
FROM charging_processes
WHERE car_id = %s AND end_date IS NOT NULL;
```

**收益**：RTT 4 → 2，节省约 50-100 ms（取决于网络延迟）。

### 2.3 案例 2：`tesla_monthly_report` 4 → 2 查询

**当前**（第 2519-2590 行）：当前月 drives + charges、前一月 drives + charges，各一次。

**优化后**：每个表只查一次，用参数化月份边界 + `FILTER` 拆开。

```sql
-- drives（当前月 + 前一月）
SELECT
    COUNT(*) FILTER (WHERE start_date >= %(cur)s AND start_date < %(next)s)            AS cur_trips,
    COALESCE(SUM(distance) FILTER (WHERE start_date >= %(cur)s AND start_date < %(next)s), 0)     AS cur_km,
    COALESCE(SUM(duration_min) FILTER (WHERE start_date >= %(cur)s AND start_date < %(next)s), 0) AS cur_min,
    COALESCE(SUM(distance) FILTER (WHERE start_date >= %(prev)s AND start_date < %(cur)s), 0)     AS prev_km
FROM drives
WHERE car_id = %(car_id)s AND distance > 0
  AND start_date >= %(prev)s AND start_date < %(next)s;  -- 限定窗口避免全表扫
```

### 2.4 案例 3：`tesla_live` / `tesla_status` 检查

两者都查"最新 positions + 车辆状态 + 软件版本"，看起来已经做了单查询优化（第 554-580 行周围），但 `tesla_live` 仍有 3 次查询（第 1815 行起），值得再 review 一遍。

---

## 三、外部依赖：Nominatim

### 3.1 问题

`tesla_trip_cost` 1296 ms 中，**800-1000 ms 是 Nominatim 的 HTTP 调用**（`nominatim.openstreetmap.org`）。同一个目的地（"万达·天樾"、"公司"）可能被问很多次，每次都打一次 OSM。

### 3.2 建议：本地文件缓存

```python
# 新增 utils：_geocode_cache.py
import json
from pathlib import Path

_GEO_CACHE_DIR  = Path.home() / ".cache" / "teslamate-mcp"
_GEO_CACHE_FILE = _GEO_CACHE_DIR / "geocode.json"
_GEO_CACHE: dict = {}

def _load_geocode_cache() -> dict:
    if _GEO_CACHE:
        return _GEO_CACHE
    if _GEO_CACHE_FILE.exists():
        _GEO_CACHE.update(json.loads(_GEO_CACHE_FILE.read_text()))
    return _GEO_CACHE

def _save_geocode_cache():
    _GEO_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _GEO_CACHE_FILE.write_text(json.dumps(_GEO_CACHE, ensure_ascii=False, indent=2))
```

在 `tesla_trip_cost` 里：

```python
cache = _load_geocode_cache()
if destination in cache:
    dest_lat, dest_lon, dest_name = cache[destination]
else:
    # ... 现有 Nominatim 调用 ...
    cache[destination] = [dest_lat, dest_lon, dest_name]
    _save_geocode_cache()
```

**收益**：重复目的地 1000 ms → <5 ms（文件读取），持久化跨进程。

### 3.3 进阶：复用 TeslaMate 本地 `addresses` 表

TeslaMate 自己把历史经停过的地方反向地理编码后存在 `addresses` 表里。完全可以先查 TeslaMate 自己有没有这个地址，找到了就用 TeslaMate 的 lat/lon，找不到才打 Nominatim。

```sql
SELECT latitude, longitude, display_name
FROM addresses
WHERE display_name ILIKE '%' || %s || '%'
   OR name ILIKE '%' || %s || '%'
LIMIT 1;
```

这对"我要去万达"这种本地化场景特别合适，直接本地 DB 命中，零外网。

---

## 四、应用层 Python

### 4.1 连接池（现状✅）

第 316-351 行已经用 `psycopg2.pool.ThreadedConnectionPool(minconn=2, maxconn=8)`，配合 `keepalive` 和 `statement_timeout=30s`。**已经是正确姿势**。

**可能需要调整**：
- `maxconn=8` 对单用户 MCP 够用，如果接多个并发 MCP 客户端或服务化部署，可调到 16-32
- `minconn=2` 保持低位是对的（避免 idle 连接浪费）

### 4.2 缓存层（现状 🟡 可加强）

**当前有**：
- `_cache`（dict + threading.Lock，TTL 默认 300s）— 第 414 行
- `ROUTINE_CACHE`（TTL 3600s）— 第 1190 行，仅服务于 routine detection

**被缓存的工具（仅 3 处 `_cached_query` 调用）**：
- `geofences`（第 456 行）
- `cars`（第 566 行）
- `car_params`（routine cache 里）

**未缓存但应该缓存的**：

| 工具 | 是否适合缓存 | 建议 TTL |
|---|---|---|
| `tesla_cars()` | ✅ 已缓存 | 现状 OK |
| `tesla_battery_health` | ✅ 数据按月粒度变化 | 3600s（1h） |
| `tesla_savings` 的 lifetime 部分 | ✅ 几乎不变 | 600s（10m） |
| `tesla_efficiency_by_temp` | ✅ 聚合类、慢变 | 1800s（30m） |
| `tesla_top_destinations` | ✅ 慢变 | 1800s |
| `tesla_monthly_report` 历史月份 | ✅ 历史数据不会变 | 86400s（1 天） |
| `tesla_status` / `tesla_live` | ❌ 必须实时 | 不缓存 |

**建议**：把 `_cached_query` 暴露给业务调用方式更方便（一个 `@cache(ttl=600)` 装饰器），然后给以上工具加缓存。

### 4.3 日志开销（次要）

51 处 `_log.info/debug/warning/error`，每次工具调用都打几条。量级不大，但生产时可以考虑：
- 把 `[TOOL] ... called` 改成 `_log.debug`
- 给 `_query` 加一个"仅超过 100ms 才打 INFO"的 SlowLog 判据

### 4.4 序列化开销（非瓶颈）

MCP 响应是字符串（markdown），`fetchall → dict → str.join` 这条路都是 Python 字符串操作，热点不在这里。无需优化。

---

## 五、索引 SQL 脚本（可直接用）

按影响排序，优先做前两个：

```sql
-- ========================================================
-- 1. battery_health 专用 (覆盖 WHERE battery_level = 100)
-- ========================================================
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_positions_battery_full
ON positions (car_id, date)
WHERE battery_level = 100 AND ideal_battery_range_km IS NOT NULL;

-- ========================================================
-- 2. tpms_history 专用 (覆盖 tpms_pressure_* IS NOT NULL)
-- ========================================================
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_positions_tpms_brin
ON positions USING BRIN (car_id, date)
WHERE tpms_pressure_fl IS NOT NULL;

-- ========================================================
-- 验证（跑完后观察命中）
-- ========================================================
-- EXPLAIN (ANALYZE, BUFFERS)
-- SELECT date_trunc('month', date), AVG(ideal_battery_range_km)
-- FROM positions
-- WHERE car_id = 1 AND battery_level = 100 AND ideal_battery_range_km IS NOT NULL
-- GROUP BY 1 ORDER BY 1 DESC LIMIT 24;

-- ========================================================
-- 回滚（如果索引效果不佳可删除）
-- ========================================================
-- DROP INDEX CONCURRENTLY IF EXISTS idx_positions_battery_full;
-- DROP INDEX CONCURRENTLY IF EXISTS idx_positions_tpms_brin;
```

**注意事项**：
- 三条 `CREATE INDEX` 在 TeslaMate DB 上跑，**不是** MCP server
- `CONCURRENTLY` 不能在事务内执行，所以脚本一条一条跑
- 预估创建时间：positions 2.39 GB / 18.6M 行 ≈ 2-5 分钟/个
- 创建期间 PG 后台消耗 CPU/IO，对 TeslaMate 正常写入影响极小

---

## 六、ROI 投入产出打分

| 建议 | 实施成本 | 预期收益 | ROI 评分 | 优先级 |
|---|---|---|---|---|
| 加 `idx_positions_battery_full` | 🟢 5 分钟 | battery_health **10-50×** | ⭐⭐⭐⭐⭐ | **P0** |
| 加 `idx_positions_tpms_brin` | 🟢 5 分钟 | tpms_history **3-10×** | ⭐⭐⭐⭐⭐ | **P0** |
| 地址先查 `addresses` 表再打 Nominatim | 🟡 30 分钟 | trip_cost 命中本地 **100×** | ⭐⭐⭐⭐⭐ | **P0** |
| Nominatim 文件缓存 | 🟢 15 分钟 | 重复目的地 **∞×** | ⭐⭐⭐⭐⭐ | **P1** |
| `tesla_savings` FILTER 合并 | 🟢 20 分钟 | **2×** | ⭐⭐⭐⭐ | **P1** |
| `tesla_monthly_report` FILTER 合并 | 🟢 20 分钟 | **2×** | ⭐⭐⭐⭐ | **P1** |
| 历史 `monthly_report` 加 1 天缓存 | 🟡 45 分钟 | 历史月 **1000×** | ⭐⭐⭐⭐ | **P2** |
| battery_health 加 1h 缓存 | 🟢 10 分钟 | **10×**（缓存命中时） | ⭐⭐⭐⭐ | **P2** |
| 连接池 maxconn 调到 16 | 🟢 1 分钟 | 并发场景 **2×** | ⭐⭐ | **P3** |
| INFO → DEBUG 日志降级 | 🟢 10 分钟 | 微幅 | ⭐ | **P3** |
| 引入 asyncpg | 🔴 1 天 | 微幅 | - | **不做** |
| 引入 Redis 缓存 | 🔴 半天 | 单人无意义 | - | **不做** |

---

## 七、具体操作建议

### 7.1 立即可做（半小时内见效）

1. 在 TeslaMate DB 服务器（192.168.66.200）上执行上面的 2 条 `CREATE INDEX CONCURRENTLY`
2. 重跑 `tesla_battery_health` 和 `tesla_tpms_history` 测试，对比 before/after
3. 把实测数字记录回 `STATS_LOGIC_REVIEW.md` 或新开 `INDEX_BENCHMARK.md`

### 7.2 下一个迭代（v1.1.0）

1. `addresses` 表兜底 + Nominatim 文件缓存 → `tesla_trip_cost`
2. `FILTER (WHERE)` 合并 → `tesla_savings` / `tesla_monthly_report`
3. 给 6 个聚合类工具加 `_cached_query` 缓存层

### 7.3 不建议投入

- **不要** async DB 驱动：psycopg2 + ThreadPool 在 MCP 单机场景下足够快，asyncpg 会引入 `cursor_factory` 等兼容性麻烦
- **不要** Redis/Memcached：单用户场景内存 dict 够用
- **不要** 改成 ORM：现在的手写 SQL 很清晰，ORM 反而会拖慢并让 LATERAL/FILTER 等 PG 特性难用

---

## 附录：实测数据

**v1.0.0 基线**（35/35 工具 · 4.4s · 平均 126 ms/次）：
- 最慢：`tesla_battery_health` 1588 ms
- 次慢：`tesla_trip_cost` 1296 ms（含 Nominatim ~1 s）
- 大部分工具：50-200 ms

**预期 v1.1.0 实施"建议 P0+P1"后**（保守估计）：
- `tesla_battery_health`：1588 → **~40 ms**（40×）
- `tesla_trip_cost`（首次地址）：1296 → **~300 ms**（查 addresses 命中）
- `tesla_trip_cost`（重复地址）：1296 → **<10 ms**（缓存命中）
- `tesla_tpms_history`：若 500 ms → **~100 ms**（5×）
- `tesla_savings` / `tesla_monthly_report`：~200-300 ms → **~100-150 ms**（2×）
- 全量 35 工具：4.4s → **~2.5s**（~1.7×）
- 平均：126 ms/次 → **~70 ms/次**

---

*报告生成：2026-04-21 22:35 · 基于 tesla.py v1.0.0 + TeslaMate PG 18.3 真实数据*
