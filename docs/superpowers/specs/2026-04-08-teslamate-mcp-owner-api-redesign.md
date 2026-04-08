# TeslaMate MCP Owner API Redesign

## Status
Approved for implementation

## Overview

将 `mcp-teslamate-fleet` 从 Fleet API 改造为使用 TeslaMate Owner API，实现：
- 读取 TeslaMate PostgreSQL 数据库中的加密 tokens（共享 ENCRYPTION_KEY）
- 通过 Tesla Owner API 获取实时车辆数据（只读）
- 保留所有 TeslaMate 历史分析功能
- 以 Docker 容器方式部署到群晖 NAS
- 提供 GitHub Actions 自动构建镜像

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                   群晖 NAS (192.168.10.200)                 │
│                                                             │
│  docker-compose.yml                                         │
│  ├── teslamate ──────────────────────────────────────────┐ │
│  │       └── ENCRYPTION_KEY (用于加密 tokens)              │ │
│  ├── database ─────────────────────────────────────────┐ │ │
│  │       └── tokens 表 (AES-256-GCM 加密的 Owner API)   │ │ │
│  └── teslamate-mcp (新增) ────────────────────────────┐ │ │ │
│          └── 直接读取 database，用 ENCRYPTION_KEY      │ │ │ │
│              解密 tokens，通过 Owner API 获取实时数据   │ │ │ │
│                                                    │ │ │ │
│  MCP Client (OpenClaw / Claude Code)               │ │ │ │
│         ◄──────────────────────────────────────────┘ │ │ │
└─────────────────────────────────────────────────────│──────┘
```

## Changes

### 移除的功能
- Fleet API 认证（`CLIENT_ID`, `CLIENT_SECRET`, `refresh_token` 刷新逻辑）
- `tokens.json` 文件依赖
- HTTP Proxy（命令才需要）
- 所有车辆命令工具（lock, unlock, climate, charge, honk 等）
- `tesla_unloack` 和 `tesla_trunk` 的 confirm 参数

### 改造的功能
- `tesla_live`: 改用 Owner API `/api/1/vehicles/{vehicle_id}/vehicle_data`
  - 通过 TeslaMate 数据库获取 Owner API tokens
  - 用 `ENCRYPTION_KEY` 解密 tokens
  - 先调用 `/api/1/vehicles` 获取 vehicle_id，再获取实时数据

### 保留的功能
- 所有 TeslaMate 历史分析工具（读 PostgreSQL）：
  - `tesla_status`, `tesla_drives`, `tesla_charging_history`
  - `tesla_battery_health`, `tesla_efficiency`, `tesla_location_history`
  - `tesla_state_history`, `tesla_software_updates`
  - `tesla_savings`, `tesla_trip_cost`, `tesla_efficiency_by_temp`
  - `tesla_charging_by_location`, `tesla_top_destinations`
  - `tesla_longest_trips`, `tesla_monthly_summary`, `tesla_vampire_drain`

## Environment Variables

```env
# TeslaMate Database (共享)
TESLAMATE_DB_HOST=database
TESLAMATE_DB_PORT=5432
TESLAMATE_DB_USER=teslamate
TESLAMATE_DB_PASS=secret
TESLAMATE_DB_NAME=teslamate
ENCRYPTION_KEY=<与teslamate的ENCRYPTION_KEY相同>

# Vehicle Config
TESLA_CAR_ID=1
TESLA_BATTERY_KWH=75
TESLA_BATTERY_RANGE_KM=525

# Cost Defaults
TESLA_ELECTRICITY_RATE=0.12
TESLA_GAS_PRICE=3.50
TESLA_GAS_MPG=28
```

## Token Acquisition

Owner API tokens 由 TeslaMate 管理，存储在 PostgreSQL `tokens` 表中：

```python
# 解密流程
1. 连接 TeslaMate PostgreSQL
2. 从 tokens 表读取 encrypted access_token 和 refresh_token
3. 用 ENCRYPTION_KEY (SHA256 hash) + AES-256-GCM 解密
4. 得到 Owner API access_token
5. 通过 /api/1/vehicles 获取 vehicle_id
6. 调用 /api/1/vehicles/{vehicle_id}/vehicle_data 获取实时数据
```

## Owner API vs Fleet API Endpoints

| 功能 | Fleet API | Owner API |
|------|-----------|-----------|
| 获取车辆列表 | N/A | `GET /api/1/vehicles` |
| 实时数据 | `/api/1/vehicles/{VIN}/vehicle_data` | `/api/1/vehicles/{vehicle_id}/vehicle_data` |
| Token 来源 | `tokens.json` | TeslaMate DB (encrypted) |
| Token 类型 | `access_token`, `refresh_token` | `access`, `refresh` |
| 车辆标识 | VIN | vehicle_id |

## Deployment

### Docker Image
- 构建：GitHub Container Registry (`ghcr.io`)
- 镜像名：`ghcr.io/<owner>/teslamate-mcp:latest`
- 多架构支持：`linux/amd64`, `linux/arm64`

### docker-compose.yml 追加
```yaml
services:
  teslamate-mcp:
    image: ghcr.io/<github-owner>/teslamate-mcp:latest
    restart: always
    environment:
      - ENCRYPTION_KEY=<your-encryption-key>
      - DATABASE_HOST=database
      - DATABASE_PORT=5432
      - DATABASE_USER=teslamate
      - DATABASE_PASS=secret
      - DATABASE_NAME=teslamate
      - TESLA_CAR_ID=1
    depends_on:
      - database
```

## GitHub Actions

1. **Build & Push** (on tag push):
   - Build Docker image
   - Push to GHCR
   - Tag with version and `latest`

2. **配置指导文档**:
   - 提供完整的 docker-compose 追加配置
   - 环境变量说明
   - MCP 客户端配置（Claude Code, OpenClaw）

## Tools (Final)

### TeslaMate History (14 tools)
- `tesla_status`, `tesla_drives`, `tesla_charging_history`
- `tesla_battery_health`, `tesla_efficiency`, `tesla_location_history`
- `tesla_state_history`, `tesla_software_updates`
- `tesla_savings`, `tesla_trip_cost`, `tesla_efficiency_by_temp`
- `tesla_charging_by_location`, `tesla_top_destinations`
- `tesla_longest_trips`, `tesla_monthly_summary`, `tesla_vampire_drain`

### Live Data (1 tool)
- `tesla_live` (Owner API, read-only)

### Enhanced Features (6 new tools)
- `tesla_driving_score(period, n, year, month)` — 驾驶评分
- `tesla_trips_by_category(category, limit)` — 按分类查询行程
- `tesla_trip_categories()` — 查看所有分类统计
- `tesla_monthly_report(year, month)` — 月度驾驶报告
- `tesla_tpms_status()` — 胎压实时状态及警告
- `tesla_tpms_history(days)` — 胎压历史

## Enhanced Features

### 1. 驾驶评分 (Driving Score)

基于急加速、急刹车、速度习惯对驾驶行为评分。

**评分维度：**
- 急加速次数和幅度（从 `drives` 表的 `power_max` 推算）
- 急刹车次数（从 `power_min` 推算）
- 最高速度 vs 路段限速（如有导航数据）
- 综合评分 0-100

**查询方式（参数）：**
- `period`: `"recent_n"` (最近N次), `"monthly"` (某月), `"yearly"` (某年)
- `car_id`: 车辆 ID（默认 1）

**工具：** `tesla_driving_score(period: str, n: int | None, year: int | None, month: int | None)`

**评分规则：**
| 行为 | 扣分 |
|------|------|
| 急加速 (power_max > 阈值) | -2分/次 |
| 急刹车 (power_min < 阈值) | -2分/次 |
| 超速 (> 120km/h) | -1分/次 |
| 基准分数 | 100分 |

### 2. 行程自动分类 (Trip Classification)

按起点/终点地理位置自动将驾驶归类为不同类别。

**分类类型：**
- `commute` — 通勤（家→公司，公司→家）
- `shopping` — 购物
- `leisure` — 休闲/出游
- `long_trip` — 长途（距离 > 100km）
- `other` — 未分类

**分类规则（基于 geofence 匹配）：**
```python
# 起点/终点匹配已知地点
if start_geofence == "home" and end_geofence == "work":
    category = "commute"
elif start_geofence == "work" and end_geofence == "home":
    category = "commute"
elif distance > 100:
    category = "long_trip"
elif "mall" or "store" in geofence_name:
    category = "shopping"
else:
    category = "other"
```

**工具：**
- `tesla_trips_by_category(category: str, limit: int)` — 按分类查询行程
- `tesla_trip_categories()` — 查看所有分类及行程数量

**扩展（未来）：** 用户可自定义分类规则（正则匹配地址关键词）

### 3. 月度驾驶报告 (Monthly Driving Report)

自动生成每月驾驶汇总，支持与上月对比。

**报告内容：**
- 总里程 (km)
- 总电耗 (kWh)
- 平均电耗 (Wh/km)
- 充电次数和总充电量
- 各分类行程占比
- 驾驶评分（月均分）
- 与上月对比（+/-%）

**工具：** `tesla_monthly_report(year: int, month: int)` — 生成指定月报告

**数据结构：**
```python
{
  "year": 2026,
  "month": 3,
  "total_distance_km": 1250.5,
  "total_energy_kWh": 215.3,
  "avg_efficiency_wh_km": 172.2,
  "charge_count": 8,
  "charge_total_kWh": 198.5,
  "category_breakdown": {"commute": 60%, "long_trip": 25%, "shopping": 15%},
  "driving_score_avg": 87,
  "vs_last_month": {"distance_delta": "+12%", "efficiency_delta": "-3%"}
}
```

### 4. 胎压监测 (TPMS Monitoring)

检测胎压异常（不一致或超出设定范围）。

**配置项：**
```env
TESLA_TPMS_FRONT_LEFT=2.3   # bar
TESLA_TPMS_FRONT_RIGHT=2.3
TESLA_TPMS_REAR_LEFT=2.1
TESLA_TPMS_REAR_RIGHT=2.1
TESLA_TPMS_MIN_THRESHOLD=2.0  # bar，低于此值警告
TESLA_TPMS_MAX_THRESHOLD=2.5  # bar，高于此值警告
```

**检测逻辑：**
- 四轮压力两两对比，差值 > 0.15 bar → 不一致警告
- 任一轮 < MIN 或 > MAX → 范围警告
- 趋势分析：某轮胎持续下降 → 慢漏气警告

**工具：**
- `tesla_tpms_status()` — 当前胎压状态（含警告）
- `tesla_tpms_history(days: int)` — 近期胎压历史

**数据来源：** `tesla_live` 中的 `tpms_pressure` 字段（实时）+ `vehicle_state` 历史

---

## Out of Scope
- 车辆控制命令
- Fleet API
- Multi-vehicle support
- Multi-driver identification
- Metric units conversion
- Home Assistant / 米家集成
