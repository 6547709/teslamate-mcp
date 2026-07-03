# TeslaMate MCP 服务器

[English](README_en.md) | **中文**

基于 **TeslaMate** PostgreSQL 数据库的 MCP 服务器。仅读取数据，不包含车辆控制功能。支持 [Claude Code](https://claude.ai/code)、[OpenClaw](https://openclaw.dev) 及所有 MCP 兼容客户端。

**上游项目：** 本项目 fork 自 [loddev/mcp-teslamate-fleet](https://github.com/lodordev/mcp-teslamate-fleet)，进行了大幅定制化改造。

---

## ✨ v1.2.3 新特性

> 能耗分类大版本 —— **0 项数据库改动**。把原本纠缠在一起的功耗指标拆分成**三种独立类别**（行驶 / 充电 / 停车），各自从原始数据源独立计算、并列展示、永不混入运算。同时新增 **露营模式** 检测。当前共 **38 个工具**，无数据库测试 **110/110 全部通过**。

- 🏕️ **`tesla_vampire_drain` 露营模式（rate-based）** —— 停车时间 **>8 小时** 且该段停车的**平均每小时耗电速率** ≥ `TESLA_CAMPING_KWH_PER_HOUR`（默认 **0.8 kWh/h**）的事件，自动标记为 `🏕️ 露营模式`。kWh 换算使用**固定 75 kWh 参考电池**——无论实际是 75 / 82 / 100 kWh 电池，阈值判定都一样。哨兵 / 第三方 app **不单独区分**，只看耗电速率。所有露营事件**保证附带停车点天气**，根因一眼可见。
- 📊 **`tesla_monthly_summary` 三列分立** —— `Drive kWh`（行驶，续航差值估算）/ `Charge kWh`（充电，会话汇总）/ `Vampire kWh`（停车，事件表聚合），三种 kWh **完全独立计算、并列展示**。`Wh/km` 现在**只用行驶 kWh**，不再被充电损耗和停车耗电污染。
- 📈 **`tesla_monthly_report` 三种能量分开** —— 行驶 / 充电 / 停车耗电各自一行，与上月对比也按类别分别给出 delta。
- 🔁 **`tesla_vampire_drain` 天气去重 bug 修复** —— 多事件路径下 `dict.fromkeys(...)` 抛 `TypeError: unhashable type: \'dict\'`，已改为基于 `id(r)` 的去重，保留首次出现顺序。
- 🏷️ **`tesla_efficiency` 标签改清楚** —— 周报的 `估算 X kWh` 改成 `行驶 X kWh`，`实际充电 Y kWh` 改成 `充电 Y kWh`，顶部加注 "Two independent metrics — never mixed"。
- 🛡️ **零天气修正已就位** — `tesla_trip_cost` 在 v1.2.3 继续保留 v1.2.3 起的行为：天气只在输出末尾以 `🌦️ Current weather` 段呈现，**绝不参与 cost 公式**（cost = kWh × 电价）。
- 📊 **测试实证** —— `test_all.py` **110/110 全部通过**（was 92）。新增 8 个露营模式用例 + 7 个三类分立用例 + 2 个 `dict.fromkeys` 回归用例。

<details>
<summary>📜 v1.2.1 天气与高德（点击展开）</summary>

- 🌦️ **新增工具 `tesla_weather`** —— 基于车辆最新 GPS 位置，通过**和风天气（QWeather）**返回实时天气：温度、体感、湿度、风力、降水、能见度、天气状况。
- 📉 **新增工具 `tesla_efficiency_by_weather`** —— 按真实天气分桶的能效分析。
- 🗺️ **高德地图（AMAP）地理编码** —— 中文地址精度远胜 Nominatim，内置 GCJ-02 → WGS-84 转换。
- 🛡️ **优雅降级** —— Key 未配置时对应功能自动关闭。

</details>

> 📌 **完整清单与历史版本**：见 [CHANGELOG.md](CHANGELOG.md)（中英双语）。
> 📌 **如何启用和风天气**：见下方 [第三方 API（可选）](#-第三方-api可选) 配置说明。
---

## 功能特性

**38 个工具**，分为七大类 — 多车辆支持，所有工具都支持可选的 `car_id` 参数

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
| `tesla_efficiency_by_weather` | **按真实天气（晴/雨/雪/雾/大风）分组的能耗对比 · 需和风天气** |
| `tesla_monthly_report` | 月度驾驶报告（含上月对比） |
| `tesla_monthly_summary` | 月度汇总表（里程/kWh/费用/能耗） |

### 🌦️ 天气增强（需和风天气 API）

| 工具 | 说明 |
|------|------|
| `tesla_weather` | **车辆当前位置的实时天气（温度/体感/湿度/风力/降水/能见度/状况）** |
| `tesla_efficiency_by_weather` | **按真实天气分组的能效分析（回填历史天气，展示相对晴天偏差）** |

> 💡 天气功能需配置 `QWEATHER_API_KEY` + `QWEATHER_API_HOST`（需自行申请，见下方配置）。未配置时这两个工具返回友好提示，其余功能不受影响。此外，配置后 `tesla_trip_cost` 会按目的地实时天气自动修正电费估算（雨 +15% / 雪 +30% / 雾 +10% / 大风 +12%）。

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

      # ── 车辆参数（多车配置）────────────────────────────
      # JSON 格式：key = TeslaMate car_id，value = {kwh, range_km}
      # 所有工具均支持 car_id 参数来查询指定车辆；设置后将覆盖单车默认值
      - TESLA_CAR_PARAMS={"1":{"kwh":78.4,"range_km":675},"2":{"kwh":82,"range_km":751}}
      #   ├─ car_id=1：Model 3P 国产高性能版（改款二 / 2021.12）：78.4 kWh, 675 km CLTC
      #   └─ car_id=2：Model YL 长续航六座版（2025.08）：82.0 kWh, 751 km CLTC
      # 如只跑单车，下面的 TESLA_BATTERY_KWH + TESLA_BATTERY_RANGE_KM 仍生效
      # - TESLA_BATTERY_KWH=78.4          # 可用电池容量（kWh，单车回退）
      # - TESLA_BATTERY_RANGE_KM=675      # 满电续航（km，单车回退）
      - TESLA_CAR_ID=1                  # 默认车辆 ID（查看 TeslaMate 仪表盘）

      # ── 胎压阈值（可选）────────────────────────────────
      # - TESLA_TPMS_MIN_THRESHOLD=2.5  # 低压警告阈值（bar）
      # - TESLA_TPMS_MAX_THRESHOLD=3.5  # 高压警告阈值（bar）

      # ── 第三方 API（可选）⚠️ 占位符，必须替换成自己申请的！────
      # 高德地图 / AMAP：提升中文地址地理编码精度（tesla_trip_cost）
      #   申请：https://lbs.amap.com → 创建应用 → 选「Web服务」类型 Key
      # - AMAP_API_KEY=xxx***                          # 你的高德 Web服务 Key
      # - TESLA_AMAP_TIMEOUT=8                          # 可选，请求超时（秒）
      # 和风天气 / QWeather：启用 tesla_weather、tesla_efficiency_by_weather、行程成本天气修正
      #   申请：https://dev.qweather.com → 控制台 → 创建项目，获取 API Key + 账号专属 Host
      #   注意：必须用账号专属 Host（形如 xxxx.re.qweatherapi.com），旧公共域名返回 403
      # - QWEATHER_API_KEY=xxx***                       # 你的和风天气 API Key
      # - QWEATHER_API_HOST=xxx***.re.qweatherapi.com   # 你的专属 Host
      # - TESLA_QWEATHER_TIMEOUT=8                       # 可选，请求超时（秒）
      # - TESLA_WEATHER_SAMPLE_MAX=60                    # 可选，天气能效分析采样行程数

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

#### 🔑 第三方 API（可选）

以下功能需要你**自行申请** API Key / Host。配置文件中的 `xxx***` 均为占位符，**必须替换成你自己的**。不配置则对应功能自动关闭，其余功能不受影响。

| 服务 | 启用的功能 | 需要的环境变量 | 申请地址 |
|------|-----------|---------------|----------|
| **高德地图 / AMAP** | 中文地址地理编码（`tesla_trip_cost` 更精准） | `AMAP_API_KEY` | [lbs.amap.com](https://lbs.amap.com) → 创建应用 → 选「**Web服务**」类型 Key |
| **和风天气 / QWeather** | `tesla_weather`、`tesla_efficiency_by_weather`、行程成本天气修正 | `QWEATHER_API_KEY` + `QWEATHER_API_HOST` | [dev.qweather.com](https://dev.qweather.com) → 控制台 → 创建项目 |

> ⚠️ **和风天气特别注意**：自 2024 年起必须使用账号**专属 API Host**（形如 `xxxx.re.qweatherapi.com`）；旧版公共域名 `devapi/api.qweather.com` 现已返回 `403 Invalid Host`。Host 可带或不带协议头 / 末尾斜杠，程序会自动归一化。

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

单文件 Python 服务器，使用 **FastMCP** 框架。直接从 TeslaMate PostgreSQL 数据库读取所有数据（可选接入高德地图 / 和风天气 API 做地理编码与天气增强）：

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
git tag v1.2.3
git push origin v1.2.3
```

镜像地址：

| Tag | 用途 |
|---|---|
| `ghcr.io/6547709/teslamate-mcp:latest` | 始终指向最新发布（当前 v1.2.3） |
| `ghcr.io/6547709/teslamate-mcp:v1.2.3` | 锁定当前版本 |
| `ghcr.io/6547709/teslamate-mcp:1.2` | 跟随 1.2.x 小版本 |
| `ghcr.io/6547709/teslamate-mcp:sha-<commit>` | 不可变 commit 引用 |

双架构：`linux/amd64` + `linux/arm64`（Docker buildx）。

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
