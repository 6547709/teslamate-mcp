# TeslaMate MCP 服务器

[English](README.md) | [中文](README_zh.md)

基于 **TeslaMate** 历史数据和 **Tesla Owner API** 实时数据的 MCP 服务器。仅读取数据，不包含车辆控制功能。支持 [Claude Code](https://claude.ai/code)、[OpenClaw](https://openclaw.dev) 及所有 MCP 兼容客户端。

**上游项目：** 本项目 fork 自 [loddev/mcp-teslamate-fleet](https://github.com/lodordev/mcp-teslamate-fleet)，进行了大幅改造，使用 TeslaMate 原生 Owner API Token（无需单独配置 Fleet API）。

---

## 功能特性

**23+ 工具**，分为四类：

| 分类 | 工具 | 数据来源 |
|------|------|---------|
| **状态** | `tesla_status`、`tesla_drives`、`tesla_charging_history`、`tesla_battery_health`、`tesla_efficiency`、`tesla_location_history`、`tesla_state_history`、`tesla_software_updates` | TeslaMate 数据库 |
| **分析** | `tesla_savings`、`tesla_trip_cost`、`tesla_efficiency_by_temp`、`tesla_charging_by_location`、`tesla_top_destinations`、`tesla_longest_trips`、`tesla_monthly_summary`、`tesla_vampire_drain`、`calculate_eco_savings_vs_ice` | TeslaMate 数据库 |
| **增强** | `tesla_driving_score`、`tesla_trips_by_category`、`tesla_trip_categories`、`tesla_monthly_report`、`tesla_tpms_status`、`tesla_tpms_history`、`generate_travel_narrative_context`、`get_vehicle_persona_status` | TeslaMate 数据库 |
| **实时** | `tesla_live`（GPS、电池、温度、充电状态） | Tesla Owner API |

### 新增工具说明

#### `calculate_eco_savings_vs_ice` — 节能减排计算器
对比特斯拉与燃油车在同一行驶里程下的成本和碳排放差异。

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `days` | `30` | 回溯天数 |
| `ice_mpg` | `8.0` | 燃油车百公里油耗（L/100km） |
| `gas_price` | `8.0` | 汽油单价（元/升） |
| `electricity_price` | `0.5` | 充电单价（元/度） |

返回 JSON：ICE 基准油耗/成本/碳排、EV 实际碳排、节省金额、减少碳排放量、种树当量。

#### `generate_travel_narrative_context` — 行车游记时间线生成器
为 LLM 生成行车游记或 Vlog 脚本提供结构化的行程上下文。

| 参数 | 说明 |
|------|------|
| `start_time` | ISO8601 开始时间 |
| `end_time` | ISO8601 结束时间 |

返回时间线 JSON 数组，每段包含起终点名称、里程、时长、气温、到达后停留时长及停留类型（重要停留/短停/无停留）。

#### `get_vehicle_persona_status` — 车辆"性格"状态面板
为 LLM 扮演"有性格的数字车辆"提供活跃度、疲劳度、极限行为和健康度指标。

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `days_lookback` | `7` | 回溯天数 |

返回 JSON：活跃度（总里程、静置占比）、疲劳度（单次最长连续行驶）、极限行为（最高车速）、健康度（吸血鬼耗电估算）、中文性格标签（元气满满/疲惫不堪/闲得发慌/悠闲自得）。

---

## 快速开始

### 部署到群晖 NAS（Docker）

本服务设计为与现有 TeslaMate 一起运行。

**1. 追加到 TeslaMate 的 `docker-compose.yml`：**

```yaml
services:
  teslamate-mcp:
    image: ghcr.io/<YOUR-GITHUB-USERNAME>/teslamate-mcp:latest
    container_name: teslamate-mcp
    restart: always
    ports:
      - "30002:8080"    # 主机端口:容器端口
    environment:
      # TeslaMate 数据库（与 teslamate 服务相同的配置）
      - TESLAMATE_DB_HOST=database
      - TESLAMATE_DB_PORT=5432
      - TESLAMATE_DB_USER=teslamate
      - TESLAMATE_DB_PASS=secret
      - TESLAMATE_DB_NAME=teslamate
      # 加密密钥（必须与 teslamate 服务的 ENCRYPTION_KEY 一致）
      - ENCRYPTION_KEY=你的teslamate加密密钥
      # HTTP 服务模式
      - MCP_TRANSPORT=streamable-http
      - HTTP_HOST=0.0.0.0
      - HTTP_PORT=8080
      # 单位与货币
      - USE_METRIC_UNITS=true      # true = 公里/摄氏度/¥/Wh/km，false = 英里/华氏度/$/Wh/mi
      - TESLA_ELECTRICITY_RATE_RMB=0.6  # 每度电价格（元）
      # 车辆参数
      - TESLA_CAR_ID=1
      - TESLA_BATTERY_KWH=75        # 电池容量（千瓦时）
      - TESLA_BATTERY_RANGE_KM=525  # 满电续航（公里）
    depends_on:
      - database
```

> **重要：** `ENCRYPTION_KEY` 必须与 teslamate 服务中配置的值一致。在 teslamate 的 `docker-compose.yml` 环境变量中查找。

**2. 启动容器：**

```bash
docker-compose up -d teslamate-mcp
```

**3. 验证运行状态：**

```bash
docker logs teslamate-mcp
```

看到以下输出表示成功：
```
Uvicorn running on http://0.0.0.0:8080 (Press CTRL+C to quit)
```

---

### 配置 MCP 客户端

#### OpenClaw

在 OpenClaw 设置中添加新的 MCP 服务器：

```json
{
  "mcpServers": {
    "teslamate": {
      "url": "http://192.168.10.200:30002/mcp"
    }
  }
}
```

#### Claude Code（`~/.claude/settings.json` 或项目 `.mcp.json`）

```json
{
  "mcpServers": {
    "tesla": {
      "url": "http://192.168.10.200:30002/mcp"
    }
  }
}
```

> **注意：** 如果 Claude Code 运行在群晖以外的设备上，请确保 30002 端口网络可达。

---

## 环境变量说明

### TeslaMate 数据库（必填）

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `TESLAMATE_DB_HOST` | *（必填）* | PostgreSQL 主机地址，同一 Docker 网络下用 `database` |
| `TESLAMATE_DB_PORT` | `5432` | PostgreSQL 端口 |
| `TESLAMATE_DB_USER` | `teslamate` | 数据库用户名 |
| `TESLAMATE_DB_PASS` | *（必填）* | 数据库密码 |
| `TESLAMATE_DB_NAME` | `teslamate` | 数据库名称 |
| `ENCRYPTION_KEY` | *（必填）* | 必须与 teslamate 服务的 `ENCRYPTION_KEY` 完全一致 |

### 服务模式

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `MCP_TRANSPORT` | `stdio` | `stdio`=命令行模式，`streamable-http`=容器模式 |
| `HTTP_HOST` | `0.0.0.0` | 绑定地址 |
| `HTTP_PORT` | `8080` | 容器内部端口 |

### 单位与货币

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `USE_METRIC_UNITS` | `false` | `true`=公制（公里/摄氏度/¥），`false`=英制（英里/华氏度/$） |
| `TESLA_ELECTRICITY_RATE_RMB` | `0.6` | 电费（元/度） |
| `TESLA_ELECTRICITY_RATE_USD` | `0.12` | 电费（美元/度，fallback） |

### 车辆参数

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `TESLA_CAR_ID` | `1` | TeslaMate 中的车辆 ID（查看 TeslaMate 仪表盘） |
| `TESLA_BATTERY_KWH` | `75` | 可用电池容量（千瓦时） |
| `TESLA_BATTERY_RANGE_KM` | `525` | 满电续航（公里） |

**常见车型参考：**

| 车型 | 电池（kWh） | 续航（km） |
|------|------------|------------|
| Model 3 标准续航 | 54 | 350 |
| Model 3 长续航 | 75 | 500 |
| Model Y 长续航 | 75 | 525 |
| Model S 长续航 | 100 | 650 |
| Model X 长续航 | 100 | 560 |

### 胎压阈值（可选）

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `TESLA_TPMS_MIN_THRESHOLD` | `2.0` | 低压警告阈值（bar） |
| `TESLA_TPMS_MAX_THRESHOLD` | `2.5` | 高压警告阈值（bar） |

### 查询限制

设为 `-1` 表示不限制返回数量。

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `TESLA_LIMIT_DRIVES` | `50` | `tesla_drives` 最大返回条数 |
| `TESLA_LIMIT_CHARGING` | `50` | `tesla_charging_history` 最大返回条数 |
| `TESLA_LIMIT_TRIP_CATEGORIES` | `100` | `tesla_trip_categories` 分析的行程数 |
| `TESLA_LIMIT_BATTERY_HEALTH` | `24` | `tesla_battery_health` 月度快照数量 |
| `TESLA_LIMIT_BATTERY_SAMPLES` | `20` | `tesla_battery_health` 回退采样数 |
| `TESLA_LIMIT_LOCATION_HISTORY` | `20` | `tesla_location_history` 位置聚类数量 |
| `TESLA_LIMIT_STATE_HISTORY` | `100` | `tesla_state_history` 状态转换数量 |
| `TESLA_LIMIT_SOFTWARE_UPDATES` | `20` | `tesla_software_updates` 软件更新数量 |
| `TESLA_LIMIT_CHARGING_BY_LOCATION` | `15` | `tesla_charging_by_location` 充电地点数量 |
| `TESLA_LIMIT_TPMS_HISTORY` | `20` | `tesla_tpms_history` 胎压历史记录数 |
| `TESLA_LIMIT_VAMPIRE_DRAIN` | `20` | `tesla_vampire_drain` 吸血鬼耗电事件数 |

---

## 工作原理

单文件 Python 服务器（~1700 行），使用 **FastMCP** 框架。两条数据路径：

```
┌─────────────┐     ┌──────────────┐
│  TeslaMate   │────▶│   Postgres   │──┐
│  (数据记录)   │     │  (TeslaMate) │  │
└─────────────┘     └──────────────┘  │   ┌───────────┐     ┌────────────┐
                                       ├──▶│ tesla.py  │────▶│ MCP 客户端  │
                                       │   │(HTTP/:8080)│     │(OpenClaw,   │
┌─────────────┐     ┌──────────────┐  │   └───────────┘     │Claude Code) │
│  Tesla       │────▶│ Owner API    │──┘                     └────────────┘
│  Owner API   │     │(Token 来自   │
└─────────────┘     │ TeslaMate DB) │
                    └──────────────┘
```

**核心机制：**
- OAuth Token 直接从 TeslaMate 的 PostgreSQL 数据库读取，使用 `ENCRYPTION_KEY` 解密
- 无需单独注册 Tesla 开发者账号或配置 Fleet API
- TeslaMate 自动处理 Token 刷新

---

## GitHub Actions 自动构建

每次打标签自动构建并推送 Docker 镜像到 GitHub Container Registry：

```bash
# 打标签发布
git tag v0.1.0
git push origin v0.1.0
```

镜像地址：`ghcr.io/<your-username>/teslamate-mcp:<tag>`

---

## 注意事项

- **单车：** 查询使用固定的 `car_id`（多车辆用户需配置不同 ID）
- **默认英制单位：** 设置 `USE_METRIC_UNITS=true` 切换为公制
- **能耗估算：** kWh 数据由续航差值估算（准确度约 90-95%）

---

## 致谢

本项目 fork 自 [@lodordev](https://github.com/lodordev) 的 [loddev/mcp-teslamate-fleet](https://github.com/lodordev/mcp-teslamate-fleet)，感谢原作者提供了 Tesla MCP 整合的基础架构。本 fork 在此基础上进行了认证方式重构（使用 TeslaMate 原生 Owner API Token）、移除车辆控制功能（提升安全性）、以及新增增强分析功能。

使用 [FastMCP](https://github.com/jlowin/fastmcp) 和 [TeslaMate](https://github.com/teslamate-org/teslamate) 构建。

---

## 开源许可

MIT
