# TeslaMate MCP 服务器

[English](README_en.md) | **中文**

基于 **TeslaMate** PostgreSQL 数据库的 MCP 服务器。仅读取数据，不包含车辆控制功能。支持 [Claude Code](https://claude.ai/code)、[OpenClaw](https://openclaw.dev) 及所有 MCP 兼容客户端。

**上游项目：** 本项目 fork 自 [loddev/mcp-teslamate-fleet](https://github.com/lodordev/mcp-teslamate-fleet)，进行了大幅定制化改造。

---

## ✨ v1.1.0 新特性

> 性能与可观测性大版本 —— **0 项数据库改动**，全部在程序层优化。冷启动延迟 ↓ 28%，热缓存 ↓ 69%。新增诊断工具。36/36 全部通过测试。

- 🔍 **新增诊断工具 `tesla_version()`** —— 返回服务端版本、工具数、Python / fastmcp / psycopg2 版本、时区、单位、**真实 DB 连通性检查**。部署后第一时间确认版本。
- 🤝 **MCP 协议元数据** —— 服务端在握手阶段直接暴露 `name=teslamate-mcp` + `version=1.1.0` + `website_url`，无需调工具客户端就能识别。
- ⚡ **SQL 查询合并（FILTER WHERE）** —— `tesla_savings` 4→2 次查询（27×）、`tesla_monthly_report` 4→2 次查询（60×），完全等价但 round-trip 减半。
- 🗺️ **`tesla_trip_cost` 三级兜底** —— 先查 TeslaMate 本地 `addresses` 表（1700+ 常去地点），再查持久化文件缓存（`~/.cache/teslamate-mcp/geocode.json`），最后才打 Nominatim。本地命中 1296ms → **~15ms（86×）**。
- 🚀 **结果级缓存框架** —— 6 个聚合慢工具加缓存：battery_health（1h）、efficiency_by_temp（30min）、charging_by_location（30min）、top_destinations（30min）、savings（10min）、monthly_report（历史月 1 天，当前月始终实时）。**缓存命中 8827× 加速！**
- 📈 **`tesla_drives` 历史窗口 +88%** —— `LIMIT_DRIVES` 500 → 1000，`tesla_drives(365+)` 覆盖从 131 天提升到 **247 天**。`days=10000` 这种超大输入现在会显示真实数据范围而非误导性的 "last 10000 days"。
- 🛡️ **Bug 修复** —— `tesla_trip_cost("")` 空串不再误命中任意地址（`ILIKE '%%'`），返回明确错误。
- 📊 **性能实证** —— 36/36 工具全通过，6/6 缓存工具 hash 完全一致，15/15 边界场景零崩溃。测试过程见 `TEST_REPORT.md` + `PERFORMANCE_IMPLEMENTATION.md`（本次发布附件）。

完整清单见 [CHANGELOG.md](CHANGELOG.md#110---2026-04-22)。

---

## 功能特性

**36 个工具**，分为六大类 — 多车辆支持，所有工具都支持可选的 `car_id` 参数

**多车辆支持：** 所有工具都支持可选的 `car_id` 参数来查询特定车辆。使用 `tesla_cars()` 列出所有已注册的车辆。

### 🚗 车辆状态

| 工具 | 说明 |
|------|------|
| `tesla_version` | **服务端版本与诊断信息（版本号、工具数、DB 连通状态、Python/fastmcp 版本）** |
| `tesla_cars` | 列出 TeslaMate 中已注册的所有车辆 |
| `tesla_status` | 当前车辆状态 — 电量、续航、位置、空调、里程 |
| `tesla_live` | 实时轮询状态（GPS、电池、温度、TPMS、充电） |
| `tesla_tpms_status` | 胎压监测，异常报警 |
| `tesla_tpms_history` | 近期胎压历史记录 |

### 📊 行程与驾驶

| 工具 | 说明 |
|------|------|
| `tesla_drives` | 最近行程列表，支持 date_from/date_to 筛选 |
| `tesla_driving_score` | 驾驶评分（加速/刹车/速度习惯） |
| `tesla_trips_by_category` | 按类别筛选行程（通勤/购物/休闲/长途/其他） |
| `tesla_trip_categories` | 各类别行程数量统计 |
| `tesla_longest_trips` | 最长行程排名 |
| `tesla_top_destinations` | 最常访问目的地 |
| `tesla_location_history` | 位置历史 — 各地点停留时长 |

### 🔋 电池与充电

| 工具 | 说明 |
|------|------|
| `tesla_charging_history` | 充电历史记录（支持 date_from/date_to） |
| `tesla_charges` | 详细充电记录（含地点和费用明细） |
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

所有配置通过环境变量完成。以下是**完整参考配置**，包含所有可用选项：

```yaml
services:
  teslamate-mcp:
    image: ghcr.io/6547709/teslamate-mcp:latest
    container_name: teslamate-mcp
    restart: always
    ports:
      - "30002:8080"              # 主机端口:容器端口
    environment:
      # ── TeslaMate 数据库（必填）─────────────────────────
      - TESLAMATE_DB_HOST=database      # PostgreSQL 主机（同一 Docker 网络下用 database）
      - TESLAMATE_DB_PORT=5432          # PostgreSQL 端口
      - TESLAMATE_DB_USER=teslamate     # 数据库用户名
      - TESLAMATE_DB_PASS=secret        # 数据库密码  ← 请修改
      - TESLAMATE_DB_NAME=teslamate     # 数据库名称

      # ── 服务模式 ───────────────────────────────────────
      - MCP_TRANSPORT=streamable-http   # stdio=命令行模式，streamable-http=容器模式
      - HTTP_HOST=0.0.0.0              # 绑定地址
      - HTTP_PORT=8080                 # 容器内部端口
      # - MCP_DEBUG=false              # 设为 true 开启详细日志

      # ── 时区 ───────────────────────────────────────────
      - TIMEZONE=Asia/Shanghai          # IANA 时区名（如 Asia/Shanghai、America/Los_Angeles）

      # ── 单位与货币 ─────────────────────────────────────
      - USE_METRIC_UNITS=true           # true=公里/摄氏度/¥/Wh/km，false=英里/华氏度/$/Wh/mi
      - TESLA_ELECTRICITY_RATE_RMB=0.6  # 电费（元/度）
      # - TESLA_ELECTRICITY_RATE_USD=0.12  # 电费（美元/度，fallback）
      # - TESLA_GAS_PRICE=3.50          # 油价（美元/加仑，用于节省计算）
      # - TESLA_GAS_MPG=28              # 燃油车油耗（MPG，用于节省计算）

      # ── 车辆参数 ───────────────────────────────────────
      - TESLA_CAR_ID=1                  # 默认车辆 ID（查看 TeslaMate 仪表盘）
      - TESLA_BATTERY_KWH=75            # 可用电池容量（kWh）
      - TESLA_BATTERY_RANGE_KM=525      # 满电续航（km）
      # 多车配置：JSON 格式，key 为车辆 ID，value 为电池参数
      # 所有工具均支持 car_id 参数来查询指定车辆
      # 设置后将覆盖上面的单车环境变量
      # - TESLA_CAR_PARAMS={"1":{"kwh":75,"range_km":525},"2":{"kwh":60,"range_km":438}}

      # ── 胎压阈值（可选）────────────────────────────────
      # - TESLA_TPMS_MIN_THRESHOLD=2.5  # 低压警告阈值（bar）
      # - TESLA_TPMS_MAX_THRESHOLD=3.5  # 高压警告阈值（bar）

      # ── 查询限制（可选，设 -1 为不限制）────────────────
      # - TESLA_LIMIT_DRIVES=500             # tesla_drives 最大返回条数
      # - TESLA_LIMIT_CHARGING=500           # tesla_charging_history 最大返回条数
      # - TESLA_LIMIT_TRIP_CATEGORIES=500    # tesla_trip_categories 分析行程数
      # - TESLA_LIMIT_BATTERY_HEALTH=60      # tesla_battery_health 月度快照数
      # - TESLA_LIMIT_BATTERY_SAMPLES=30     # tesla_battery_health 回退采样数
      # - TESLA_LIMIT_LOCATION_HISTORY=50    # tesla_location_history 位置聚类数
      # - TESLA_LIMIT_STATE_HISTORY=500      # tesla_state_history 状态转换数
      # - TESLA_LIMIT_SOFTWARE_UPDATES=30    # tesla_software_updates 软件更新数
      # - TESLA_LIMIT_CHARGING_BY_LOCATION=50  # tesla_charging_by_location 充电地点数
      # - TESLA_LIMIT_TPMS_HISTORY=60        # tesla_tpms_history 胎压历史数
      # - TESLA_LIMIT_VAMPIRE_DRAIN=50       # tesla_vampire_drain 掉电事件数
    depends_on:
      - database
```

> 💡 注释掉的变量（`#`）显示的是默认值，只需取消注释并修改你需要的即可。

**车型参考（中国）：**

| 年份 | 车型 | 版本 | 电池（kWh） | 续航NEDC（km） | 电池类型 | 备注 |
|------|------|-------|------|------|-------|-------|
| 2014-2016 | Model S | 早期进口系列（60/75/85/90） | 60-90 | 280-440 | 早期 18650 三元锂 |
| 2016-2018 | Model S/X | 100D 系列（进口） | 100.0 | 450-510 | 松下 18650 三元锂 |
| 2019.02 | Model 3 | 进口高性能/长续后驱版 | 75.0 | 490 | 松下 2170 三元锂 |
| 2019.05 | Model 3 | 进口标准续航升级版 | 52.0 | 380 | 松下 2170 三元锂 |
| 2019.12 | Model 3 | 国产标续版（首批） | 52.5 | 445 | 宁德时代 LFP/三元锂 |
| 2020.04 | Model 3 | 国产长续航后驱版 | 75.0 | 668 | LG 三元锂 |

| 年份 | 车型 | 版本 | 电池（kWh） | 续航CLTC（km） | 电池类型 | 备注 |
|------|------|-------|------|------|-------|-------|
| 2021.01 | Model Y | 国产长续航/高性能版 | 76.8/78.4 | 594-640 | LG 三元锂 |
| 2021.02 | Model 3 | 国产高性能版（P版）改款一 | 76.8 | 605 | LG M50 (早期) |
| 2021.07 | Model Y | 国产后轮驱动版（标续） | 60.0 | 525 | 宁德时代 LFP |
| 2021.11 | Model 3 | 国产后轮驱动版（60度） | 60.0 | 556 | 宁德时代 LFP |
| 2021.12 | Model 3 | 国产高性能版（P版）改款二 | 78.4 | 675 | LG 5L (新款) | AMD Ryzen芯片
| 2023.01 | Model S/X | 新款（Plaid/双电机） | 100.0 | 664-715 | 三元锂（18650 改进版） |
| 2023.09 | Model 3 | 焕新版 后驱/长续航 | 60/78.4 | 606-713 | LFP/三元锂 |
| 2024.04 | Model 3 | 焕新版 高性能版（P版） | 78.4 | 623 | LG 三元锂 |
| 2024.10 | Model Y | 国产标续航/长续航（微改） | 60/78.4 | 554-688 | LG 三元锂 |辅助驾驶硬件 HW4.0
| 2025.01 | Model 3+ | 焕新版超长续航后驱版 | 78.4 | 713| 三元锂 (针对能效优化) |
| 2025.05 | Model Y | 焕新版 后驱/长续航 | 60/78.4 | 593-750| 三元锂 (针对能效优化) |
| 2025.08 | Model YL | 长续航六座版 | 82.0 | 751 | 三元锂 |首款6座
| 2026.03 | Model Y | 焕新版 后驱/长续航 | 60/78.4 | 593-750 | LG 三元锂 |内饰黑化、屏幕16寸


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

---

## 工作原理

单文件 Python 服务器（~3700 行），使用 **FastMCP** 框架。直接从 TeslaMate PostgreSQL 数据库读取所有数据：

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
