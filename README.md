# TeslaMate MCP 服务器

[English](README_en.md) | [中文](README.md)

基于 **TeslaMate** PostgreSQL 数据库的 MCP 服务器。仅读取数据，不包含车辆控制功能。支持 [Claude Code](https://claude.ai/code)、[OpenClaw](https://openclaw.dev) 及所有 MCP 兼容客户端。

**上游项目：** 本项目 fork 自 [loddev/mcp-teslamate-fleet](https://github.com/lodordev/mcp-teslamate-fleet)，进行了大幅定制化改造。

---

## 功能特性

**33 个工具**，分为七大类 — 全部只读查询 TeslaMate PostgreSQL：

### 🚗 车辆状态

| 工具 | 说明 |
|------|------|
| `tesla_status` | 当前车辆状态 — 电量、续航、位置、空调、里程 |
| `tesla_live` | 实时轮询状态（GPS、电池、温度、TPMS、充电） |
| `tesla_tpms_status` | 胎压监测，异常报警 |
| `tesla_tpms_history` | 近期胎压历史记录 |

### 📊 行程与驾驶

| 工具 | 说明 |
|------|------|
| `tesla_drives` | 最近 N 天行程列表 |
| `tesla_driving_score` | 驾驶评分（加速/刹车/速度习惯） |
| `tesla_trips_by_category` | 按类别筛选行程（通勤/购物/休闲/长途/其他） |
| `tesla_trip_categories` | 各类别行程数量统计 |
| `tesla_longest_trips` | 最长行程排名 |
| `tesla_top_destinations` | 最常访问目的地 |
| `tesla_location_history` | 位置历史 — 各地点停留时长 |

### 🔋 电池与充电

| 工具 | 说明 |
|------|------|
| `tesla_charging_history` | 充电历史记录 |
| `tesla_charging_by_location` | 各充电地点的充电模式（支持日期过滤） |
| `tesla_battery_health` | 电池衰减趋势（100% 电量续航变化） |
| `tesla_vampire_drain` | 驻车掉电分析（过夜电池损耗） |

### ⚡ 能耗分析

| 工具 | 说明 |
|------|------|
| `tesla_efficiency` | 能耗趋势（Wh/km 每周平均） |
| `tesla_efficiency_by_temp` | 不同温度下的能耗曲线 |
| `tesla_monthly_report` | 月度驾驶报告（含上月对比） |
| `tesla_monthly_summary` | 月度汇总表（里程/kWh/费用/能耗） |

### 💰 省钱 & 环保

| 工具 | 说明 |
|------|------|
| `tesla_savings` | 油费节省 scorecard |
| `tesla_trip_cost` | 估算到某目的地的电费（kWh/费用/续航检查） |
| `calculate_eco_savings_vs_icev` | 相比燃油车的节省 + CO₂ 减排 + 种树当量 |

### 🏆 成就 & 趣味

| 工具 | 说明 |
|------|------|
| `check_driving_achievements` | 检测驾驶成就（极限续航幸存者/午夜幽灵/冰雪勇士） |
| `generate_travel_narrative_context` | 旅行叙事时间线（用于写游记/Vlog 脚本） |
| `generate_weekend_blindbox` | 周末盲盒目的地推荐（去过一次的独特记忆） |
| `generate_monthly_driving_report` | 精美 Markdown 月报（含 Emoji） |
| `get_vehicle_persona_status` | 车辆人设状态（活跃度/疲劳度/极端情况/健康度） |
| `get_charging_vintage_data` | 单次充电详细物理参数 |
| `get_driver_profile` | 驾驶者档案 — 等级、成就、彩蛋 |
| `check_daily_quest` | 今日随机驾驶挑战任务 |
| `get_longest_trip_on_single_charge` | 单次充电最长行驶距离 |

### 🔧 系统与历史

| 工具 | 说明 |
|------|------|
| `tesla_state_history` | 车辆状态转换历史（在线/睡眠/离线） |
| `tesla_software_updates` | 固件版本历史 |

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

### 服务模式

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `MCP_TRANSPORT` | `stdio` | `stdio`=命令行模式，`streamable-http`=容器模式 |
| `HTTP_HOST` | `0.0.0.0` | 绑定地址 |
| `HTTP_PORT` | `8080` | 容器内部端口 |

### 时区与显示

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `TIMEZONE` | `Asia/Shanghai` | 所有输出日期的时区（IANA 时区名，如 `Asia/Shanghai`、`America/Los_Angeles`） |

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

**车型参考（中国）：**

| 年份 | 车型 | 版本 | 电池（kWh） | 续航（km） | 备注 |
|------|------|------|------------|------------|------|
| 2014-2016 | Model S | 早期进口系列（60/75/85/90） | 60-90 | 280-440 | 早期 18650 三元锂 |
| 2016-2018 | Model S/X | 100D 系列（进口） | 100.0 | 450-510 | 松下 18650 三元锂 |
| 2019.02 | Model 3 | 进口高性能/长续后驱版 | 75.0 | ~490 | 松下 2170 三元锂 |
| 2019.05 | Model 3 | 进口标准续航升级版 | 52.0 | ~380 | 松下 2170 三元锂 |
| 2019.12 | Model 3 | 国产标续版（首批） | 52.5 | ~380 | 宁德时代 LFP/三元锂 |
| 2020.04 | Model 3 | 国产长续航后驱版 | 75.0 | ~490 | LG 三元锂 |
| 2021.01 | Model Y | 国产长续航/高性能版 | 76.8/78.4 | 480-505 | LG 三元锂 |
| 2021.07 | Model Y | 国产后轮驱动版（标续） | 60.0 | ~435 | 宁德时代 LFP |
| 2021.11 | Model 3 | 国产后轮驱动版（60度） | 60.0 | ~439 | 宁德时代 LFP |
| 2022.03 | Model 3 | 2022款 高性能版（P版） | 78.4 | ~507 | LG 三元锂 |
| 2023.01 | Model S/X | 新款（Plaid/双电机） | 100.0 | 520-620 | 三元锂（18650 改进版） |
| 2023.09 | Model 3 | 焕新版 后驱/长续航 | 60/78.4 | 438-550 | LFP/三元锂 |
| 2024.04 | Model 3 | 焕新版 高性能版（P版） | 78.4 | ~480 | LG 三元锂 |
| 2025.01 | Model 3+ | 焕新版超长续航后驱版 | 78.4 | ~620 | 三元锂（新款） |
| 2025.03 | Model Y L | 长续航六座版 | 82.0 | ~580 | 三元锂 |

### 胎压阈值（可选）

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `TESLA_TPMS_MIN_THRESHOLD` | `2.0` | 低压警告阈值（bar） |
| `TESLA_TPMS_MAX_THRESHOLD` | `2.5` | 高压警告阈值（bar） |

### 查询限制

设为 `-1` 表示不限制返回数量。

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `TESLA_LIMIT_DRIVES` | `500` | `tesla_drives` 最大返回条数 |
| `TESLA_LIMIT_CHARGING` | `500` | `tesla_charging_history` 最大返回条数 |
| `TESLA_LIMIT_TRIP_CATEGORIES` | `500` | `tesla_trip_categories` 分析的行程数 |
| `TESLA_LIMIT_BATTERY_HEALTH` | `60` | `tesla_battery_health` 月度快照数量 |
| `TESLA_LIMIT_BATTERY_SAMPLES` | `20` | `tesla_battery_health` 回退采样数 |
| `TESLA_LIMIT_LOCATION_HISTORY` | `50` | `tesla_location_history` 位置聚类数量 |
| `TESLA_LIMIT_STATE_HISTORY` | `500` | `tesla_state_history` 状态转换数量 |
| `TESLA_LIMIT_SOFTWARE_UPDATES` | `20` | `tesla_software_updates` 软件更新数量 |
| `TESLA_LIMIT_CHARGING_BY_LOCATION` | `50` | `tesla_charging_by_location` 充电地点数量 |
| `TESLA_LIMIT_TPMS_HISTORY` | `30` | `tesla_tpms_history` 胎压历史记录数 |
| `TESLA_LIMIT_VAMPIRE_DRAIN` | `50` | `tesla_vampire_drain` 吸血鬼耗电事件数 |

---

## 工作原理

单文件 Python 服务器（~2700 行），使用 **FastMCP** 框架。直接从 TeslaMate PostgreSQL 数据库读取所有数据：

```
┌─────────────┐     ┌──────────────┐     ┌───────────┐     ┌────────────┐
│  TeslaMate   │────▶│   Postgres   │────▶│ tesla.py  │────▶│ MCP 客户端  │
│  (数据记录)   │     │  (TeslaMate) │     │(HTTP/:8080)│     │(OpenClaw,   │
└─────────────┘     └──────────────┘     └───────────┘     │Claude Code) │
                                                            └────────────┘
```

**核心机制：**
- 所有数据直接来自 TeslaMate PostgreSQL 数据库，无需 Tesla Owner API
- 无需单独注册 Tesla 开发者账号或配置任何 API Token

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

本项目 fork 自 [@lodordev](https://github.com/lodordev) 的 [loddev/mcp-teslamate-fleet](https://github.com/lodordev/mcp-teslamate-fleet)，感谢原作者提供了 Tesla MCP 整合的基础架构。本 fork 在此基础上移除了车辆控制功能（提升安全性）、所有数据仅从 TeslaMate 数据库读取（无需任何 Tesla API Token）、以及新增增强分析功能。

使用 [FastMCP](https://github.com/jlowin/fastmcp) 和 [TeslaMate](https://github.com/teslamate-org/teslamate) 构建。

---

## 开源许可

MIT
