# teslamate-mcp 工具统计逻辑合理性评估

> 评估时间：2026-04-21
> 代码版本：已包含 P0/P1/P2/P3 修复（+611/-286 行）
> 评估对象：35 个 MCP 工具

**评级说明**
- 🟢 合理：逻辑清晰、数据源恰当、边界处理完备
- 🟡 有瑕疵：能用，但有小缺陷或改进空间（例：采样偏差、显示口径不一致）
- 🔴 有问题：应修复（例：指标偏离定义、关键 bug）

---

## 一、车辆状态（5）

### 1. `tesla_cars`
- **干什么**：列出 TeslaMate 中所有注册车辆
- **数据源**：`cars` 表（id、name、model、vin、efficiency）
- **核心逻辑**：`SELECT ... FROM cars ORDER BY display_priority, id`；拼接输出各车信息 + 是否为默认
- **评估**：🟢 直接从 `cars` 表查询，无统计计算，没问题

---

### 2. `tesla_status`
- **干什么**：当前车辆综合状态（电量、续航、位置、空调、最近充电、软件版本）
- **数据源**：`positions`（最新）+ `states`（最新）+ `charging_processes`（最新）+ `updates`（最新）+ `cars`（缓存）+ `geofences`（缓存）
- **核心逻辑**：
  - 最新 position：`ORDER BY id DESC LIMIT 1`
  - 最新充电：`ORDER BY start_date DESC NULLS LAST`（Bug #2 修复后）
  - 续航估算：`BATTERY_RANGE_KM × battery_level / 100`（配置 × 百分比）
- **评估**：🟡
  - 续航 **用配置而非实际 `ideal_battery_range_km`**。长期用车后 battery 衰减，配置值不更新会高估续航。建议优先读 `positions.ideal_battery_range_km`（已存储的真实值），falls back 到配置
  - 判定"正在充电"用 `charge_end IS NULL AND charge_start IS NOT NULL`：若 TeslaMate 之前充电但 end_date 未回写（断网等异常），会误判成"正在充电"。可加条件 `start_date >= NOW() - INTERVAL '24 hours'`

---

### 3. `tesla_live`
- **干什么**：和 `tesla_status` 类似，但字段更全（含 TPMS、功率、加速度）
- **数据源**：同上 + TPMS 字段
- **核心逻辑**：同 status，外加 TPMS 4 轮读数
- **评估**：🟡
  - 和 `tesla_status` 有 70% 重叠 —— 建议统一一个实现减少代码重复（工程问题，非统计）
  - 续航问题同 `tesla_status`

---

### 4. `tesla_tpms_status`
- **干什么**：当前胎压 + 低/高报警 + 4 轮差异检查
- **数据源**：`positions`（最新含 TPMS 非空的记录）
- **核心逻辑**：
  - 取最新一条 TPMS 非空的 position
  - 与 `TPMS_MIN/MAX` 阈值比较
  - 4 轮平均值，任一轮偏离平均 > `TPMS_WARN_DELTA (0.2 bar)` 报警
- **评估**：🟢 逻辑合理，阈值可通过环境变量配置
  - 小瑕疵：docstring 提到"> 0.15 bar"但代码是 `TPMS_WARN_DELTA = 0.2 bar`，文档不一致

---

### 5. `tesla_tpms_history`
- **干什么**：近 N 天 TPMS 读数时间序列
- **数据源**：`positions` 的 4 个 tpms_pressure_* 字段
- **核心逻辑**：过滤 TPMS 非空 + 时间范围，按 date DESC 取 `LIMIT_TPMS_HISTORY (60)` 条
- **评估**：🟡
  - 60 条对"30 天历史"来说偏少（1900 万 positions 里 TPMS 非空可能每几分钟一条），很容易只看到最近 1 天
  - 建议按日聚合（每天一个平均值 + min/max）而不是取原始采样

---

## 二、行程与驾驶（7）

### 6. `tesla_drives`
- **干什么**：列出近期每次驾驶 + 单次能耗
- **数据源**：`drives` + `addresses`
- **核心逻辑**：
  - 单次能耗 = `max(0, (start_ideal_range - end_ideal_range) × kwh_per_km)`
  - 总能耗/效率由单次累加
- **评估**：🟡
  - 单次用 `ideal_range` 差估算有系统性偏差（能量回收为负被夹成 0），但 drives 表**没有真实能耗字段**，这是不得已选择 —— 输出里已加"*注：单次能耗基于续航差值估算*"提示（Bug #6 修复）
  - `kwh_per_km` 是常量 `BATTERY_KWH / BATTERY_RANGE_KM`，**不反映车辆实际效率**

---

### 7. `tesla_driving_score`
- **干什么**：驾驶安全评分（100 分制）基于加速/刹车/速度
- **数据源**：`drives`（power_max、power_min、speed_max、duration_min）
- **核心逻辑**：
  - 硬加速（power_max > 50 kW）扣分
  - 硬刹车（power_min < -30 kW）扣分
  - 高速（speed_max > 130 km/h）扣分
  - 每项最多扣 5 分或 3 分；评分 = `max(0, 100 - avg_deduct × 10)`
- **评估**：🔴
  - **阈值硬编码**（`POWER_ACCEL_THRESHOLD=50`、`SPEED_THRESHOLD_KMH=130`），对不同车型/驾驶风格不合理
  - **"速度 > 130"一刀切**：在高速公路上跑 130 合法合规，不应扣分；但对市区驾驶 50km/h 其实已经危险
  - **扣分权重**（×10）缺乏依据，单次扣 2 次就掉 20 分
  - **`power_max > 50 kW`**：Tesla Model 3P 能轻松 200+ kW 加速，50 kW 门槛过低 —— 日常几乎每次都中招
  - 改进方案：
    - 阈值按车型或用户偏好可配置
    - 结合 `outside_temp_avg`（冬天低温下正常提速功率需求更高）
    - 速度阈值结合道路类型（通过 geofence 推断）或取最大瞬时速度分位数

---

### 8. `tesla_trips_by_category`
- **干什么**：按类别筛选行程（commute/shopping/leisure/long_trip/other）
- **数据源**：`drives` + `addresses`；`_classify_trip` 分类器
- **核心逻辑**（修复后）：
  - `long_trip`（距离 > 100 km）：SQL 端直接过滤，快路径
  - `commute`（home↔work 且 1 ≤ 距离 ≤ 100）：SQL 端 AND 条件过滤
  - 其他：循环拉取 + Python 端分类
- **评估**：🟡
  - 分类器对**中文地址**识别较弱：`shopping_keywords = ["mall", "store", "shop", ...]` 都是英文，对"万达广场""世纪金源"这种中文命名识别不出
  - `home/work` 靠访问频率自动识别，**跨城用户容易误判**（你自己的案例：识别出"西安 ↔ 成都"两地，但那是跨省长途不是通勤）
  - 改进：
    - 词典增加中文关键词
    - `home/work` 识别增加"同一城市"约束

---

### 9. `tesla_trip_categories`
- **干什么**：各类别行程数量统计（比例）
- **数据源**：最近 500 条 drive（`LIMIT_TRIP_CATEGORIES`）
- **核心逻辑**：拿最近 500 条做 `_classify_trip` 统计
- **评估**：🟡
  - **只看最近 500 条** —— 对长期用户样本不够代表；但若改成全量会随数据量增长变慢
  - 本次实测：`other 97% / long_trip 3%` —— 合理性取决于分类器质量（见上面 🟡）
  - 建议：增加 `days/start_date/end_date` 参数让用户自选时间窗

---

### 10. `tesla_longest_trips`
- **干什么**：距离排序 TOP N
- **数据源**：`drives`
- **核心逻辑**：`ORDER BY distance DESC LIMIT N`
- **评估**：🟢 简单粗暴，没问题。单次能耗和 `tesla_drives` 一样用续航差估算，已标注

---

### 11. `tesla_top_destinations`
- **干什么**：最常访问地址 TOP N（按 end_address_id 聚合）
- **数据源**：`drives` + `addresses`
- **核心逻辑**：`GROUP BY end_address_id ORDER BY COUNT(*) DESC`；`distance > 1` 过滤无意义停车
- **评估**：🟡
  - 同一个目的地因 GPS 漂移可能对应多个 `address_id`（比如停在小区不同单元楼会解析出不同 display_name） → 统计被分散
  - 改进：考虑按坐标聚类（`ROUND(lat, 3), ROUND(lon, 3)`）或按 `geofence_id` 聚合

---

### 12. `tesla_location_history`
- **干什么**：近期位置聚合，按"停留点"展示
- **数据源**：`positions`
- **核心逻辑**：
  - 把 lat/lon `ROUND(3)` 降精度（约 100m 误差）
  - `GROUP BY (lat3, lon3)` 聚合成簇
  - 按 `position_count` 排序
- **评估**：🟡
  - `position_count` ≠ **停留时间**。如果 TeslaMate 采样率不均（快速开车 vs 长时间停留），"点数"不等于"时间"
  - 文档说"time at each location"，但实际返回的是"点数"，口径不一致
  - 改进：用 `MAX(date) - MIN(date)` 作为停留时长更准；或用 `positions` 时间间隔累加

---

## 三、电池与充电（5）

### 13. `tesla_charging_history`
- **干什么**：近 N 天充电会话列表
- **数据源**：`charging_processes` + `geofences` + `addresses`（修复后直接 JOIN `address_id`）
- **核心逻辑**：`WHERE end_date IS NOT NULL`（只看已完成）按 start_date DESC 列
- **评估**：🟢 逻辑合理，展示字段齐全

---

### 14. `tesla_charges`
- **干什么**：同上但更详细（含 end_date、city/country）
- **数据源**：同上
- **核心逻辑**：同上
- **评估**：🟢 与 `tesla_charging_history` 高度重复。工程建议：合并或明确差异用途

---

### 15. `tesla_charging_by_location`
- **干什么**：分地点的充电模式（次数、总 kWh、费用）
- **数据源**：`charging_processes` + `geofences`（优先）+ `addresses`
- **核心逻辑**：`GROUP BY location`；`COALESCE(gf.name, a.display_name)`
- **评估**：🟢 合理。TOP 1 是"华润24城"24 次 377 kWh，符合"家充电"模式

---

### 16. `tesla_battery_health`
- **干什么**：100% 电量下的平均续航随月份变化 → 电池衰减曲线
- **数据源**：`positions`（battery_level=100 的记录）
- **核心逻辑**：
  - `WHERE battery_level=100 GROUP BY month` 月均 `ideal_battery_range_km`
  - 首月 vs 最近月 → 衰减百分比
- **评估**：🟡
  - **只取 100% 的采样点** —— 如果用户很少充到 100%，样本会非常稀疏（你的数据是好的，每月几十到上百样本）
  - 未排除**异常样本**：如果某次刚校准后读数异常高，会拉偏月均值
  - **退化率不考虑温度**：冬天的 ideal_range 本来就比夏天低，月份比较可能把季节效应误算成衰减
  - 性能：实测 1568 ms（Top 1 慢查询），建议 DB 层加索引
  - 改进：按年比较（跨季节），或对同月份做同比

---

### 17. `tesla_vampire_drain`
- **干什么**：驻车掉电（dry drain）
- **数据源**：`drives` + `charging_processes` + `positions`（通过 position_id JOIN）
- **核心逻辑**（修复后）：
  - 用"事件表"思路：drive_end → 下次 drive_start 或 charge_start 之间即为"停放期"
  - `drain = battery_level_before - battery_level_after`
  - 时间窗 8~168 小时（Bug #11 修复后）
- **评估**：🟢 修复后合理
  - 注意：**大部分现代特斯拉的 vampire drain 极低**（<0.1%/hr），实测你的数据 0.13%/hr 正常
  - 小瑕疵：未排除"哨兵模式开启导致的非 vampire 损耗"（Tesla 的 sentry 模式会持续掉电但不算异常）—— 但 TeslaMate 没记录 sentry 状态，改不了

---

## 四、能耗分析（4）

### 18. `tesla_efficiency`
- **干什么**：每周 Wh/km 趋势 + 平均温度
- **数据源**：`drives`
- **核心逻辑**：
  - `GROUP BY date_trunc('week', start_date)`
  - 周能耗 = `SUM(GREATEST(ideal_range diff, 0) × kwh_per_km)`
  - 效率 = `kwh × 1000 / km`
- **评估**：🟡 能耗源的问题与 `tesla_drives` 一致，输出已加估算提示。改进同 Bug #6

---

### 19. `tesla_efficiency_by_temp`
- **干什么**：不同温度区间的能耗曲线
- **数据源**：`drives`
- **核心逻辑**：
  - `CASE WHEN outside_temp_avg < 0 THEN '...' ...` 分桶
  - 桶内 SUM(kwh) / SUM(km)
- **评估**：🟢 思路合理，实测你的数据呈 U 型曲线（冷热都费电，10-20°C 最省）—— 符合物理直觉
  - 小瑕疵：英制/公制的桶定义不同（英制按华氏，公制按摄氏），展示时用映射表转换，**但边界阈值还是英制的**（`< 4.4` 对应 40°F 不是整数 4°C）。不影响正确性但不好看
  - 改进：公制用整 5/10°C 的桶

---

### 20. `tesla_monthly_report`
- **干什么**：单月驾驶报告（trips/km/kWh/cost）+ 与上月对比
- **数据源**：`drives`（距离）+ `charging_processes`（能耗/成本）
- **核心逻辑**（修复后）：
  - 能耗优先 `charging_processes.charge_energy_added`（真实充电量）
  - 无充电记录则 fallback `ideal_range` 估算
- **评估**：🟢 修复后逻辑合理
  - 小瑕疵：上月对比只看 km 和 kwh 涨跌 %，**没看效率变化**；也没做异常值检测（比如当月一次长途跨省导致 kWh 爆表）

---

### 21. `tesla_monthly_summary`
- **干什么**：最近 N 月的逐月汇总表（trips/km/kWh/Wh/km/cost）
- **数据源**：同上
- **核心逻辑**：同上，但批量按月 GROUP
- **评估**：🟢 修复后格式化正确（Bug C）
  - 小瑕疵：月份显示仍用 UTC 时区 `date_trunc('month', start_date)` —— 跨时区用户某些月份的首尾几小时可能归错（和 `generate_monthly_driving_report` 同类问题，但这里没修）
  - 建议：同 #14 统一用 `date_trunc('month', start_date AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Shanghai')`

---

## 五、省钱 & 环保（3）

### 22. `tesla_savings`
- **干什么**：累计+当月 油费 vs 电费对比
- **数据源**：`drives`（距离）+ `charging_processes`（实际 kWh）
- **核心逻辑**（修复后）：
  - 真实 kWh × 电价 = 电费
  - 距离 × (L/100km or mpg) × 油价 = 油费
  - 差额 = saved
- **评估**：🟢 修复后公制分支也正确
  - 小瑕疵：**没区分家充电 vs 公共充电**。家充 RMB0.6/kWh，公共超充可能 RMB2+/kWh —— 用固定单价会低估真实成本
  - 改进：优先用 `cp.cost` 字段（TeslaMate 可以记录实际充电费用），falls back 到固定电价

---

### 23. `tesla_trip_cost`
- **干什么**：估算到某目的地的单程/往返电费 + 续航是否够
- **数据源**：`positions`（当前位置）+ `drives`（30天平均效率）+ Nominatim API
- **核心逻辑**（修复后）：
  - Nominatim 地理编码 → 目的地坐标
  - 球面距离公式 × 1.3（估算道路系数）= 公路里程
  - 30 天平均 Wh/km × 距离 = 估算 kWh
  - 比较满电续航判断"能不能到"
- **评估**：🟡
  - **道路系数 1.3 硬编码** —— 市区/高速差异大，高速可能 1.05，山路 1.5
  - 效率用 30 天平均，不考虑"跨省高速 vs 市区通勤"的差异（高速电耗偏高）
  - 没考虑空调/载重/风向
  - 改进：用更好的地图 API（含实际路径和估算时间），或用户可传 `expected_speed_kmh` 等提示

---

### 24. `calculate_eco_savings_vs_icev`
- **干什么**：与燃油车对比，计算省钱 + CO₂ 减排 + 等价种树数
- **数据源**：`drives`（距离）+ `charging_processes`（kWh + 成本）
- **核心逻辑**：
  - ICEV 假设 L/100km × 油价 = 油费
  - EV 实际充电量 × 电价 = 电费
  - CO₂：油 2.3 kg/L、电 0.58 kg/kWh（中国电网平均）
  - 种树当量 = CO₂ / 18 kg/树/年
- **评估**：🟡
  - **ICEV 参数全用默认值**（mpg_L_per_100km=8、油价=8 RMB）用户要手动传才准
  - 0.58 kg/kWh 是全国电网均值，**用户实际所在地区不同**（四川水电多，北方煤电多）
  - "18 kg CO₂/树/年" —— 不同树种/年龄差异大，这是粗估
  - 本质是**对比模型**而非科学指标，作为娱乐/激励功能可接受
  - 改进：把假设参数在输出里明确列出（现在已经列了 ✓）

---

## 六、成就 & 趣味（9）

### 25. `check_driving_achievements`
- **干什么**：检测 3 个成就（极限续航幸存者/午夜幽灵/冰雪勇士）
- **数据源**：`charging_processes` + `drives`
- **核心逻辑**：
  - 极限续航：`start_battery_level <= 5`
  - 午夜幽灵：凌晨 0-5 点驾驶 >= 3 次（Bug #1 修复）
  - 冰雪勇士：`outside_temp_avg < 0 AND distance > 20`
- **评估**：🟢 修复后逻辑清晰，阈值合理。作为游戏化激励没问题
  - 注意：成就一旦达成就"永久"显示（每次调用都返回），没有"已解锁 vs 本期新获得"的状态管理 —— 但这是产品设计问题不是 bug

---

### 26. `generate_travel_narrative_context`
- **干什么**：指定时间段的驾驶时间线（给 LLM 生成游记）
- **数据源**：`drives` + `addresses`
- **核心逻辑**（修复后）：
  - 时区正确转换后查询
  - 按 start_date ASC 排序
  - 两段 drive 之间的时间差 > 60 min 标注为 "important_stop"
- **评估**：🟢 修复后时区正确
  - 小瑕疵：stay_after_arrival 计算**只看下一个 drive**，不区分"停车过夜"和"短暂停留"；用户跨天可能显示成"important_stop 733 分钟"这种不直观
  - 改进：>= 8h 的 gap 可标注为"overnight_stop"

---

### 27. `generate_weekend_blindbox`
- **干什么**：从历史访问的"独特地点"里随机选一个作为"周末记忆盲盒"
- **数据源**：`drives` + `addresses`
- **核心逻辑**：
  - `visit_count = 1`（只去过一次的地点）
  - 停留 >= min_stay_hours
  - 排除关键词 "家/office" 等
  - `random.choice` 选一个
- **评估**：🟢 有趣且逻辑合理
  - 小瑕疵：时间范围用 `months_lookback × 30 天` 估算，不是严格月份边界
  - 排除关键词又是英文 + 少量中文，中文覆盖不全

---

### 28. `generate_monthly_driving_report`
- **干什么**：Markdown 格式月度报告（精美版）
- **数据源**：`drives` + `charging_processes` + vampire 查询
- **核心逻辑**（修复后）：
  - 月份边界按 USER_TZ
  - 能耗优先 charging_processes，fallback ideal_range
  - 综合评分 = 100 - eff_penalty - speed_penalty - vampire_penalty
- **评估**：🟡
  - 评分维度固定（效率/速度/vampire），不考虑其他（充电频率、驾驶时段等）
  - `eff_penalty = max(0, int((avg_eff_wh_km - 150) / 10))` —— **阈值 150 Wh/km 太严格**，Model Y/3P 在北方冬天 200+ 很常见
  - `speed_penalty = 2 if max_speed_kmh > 130`：只看最高瞬时速度（可能是 GPS 抖动），一次高速就扣分
  - 改进：阈值按车型可配，或按用户个人均值的分位数

---

### 29. `get_vehicle_persona_status`
- **干什么**：车辆"人设"状态（活跃度/疲劳度/vampire）+ 判定 persona
- **数据源**：`drives` + `states` + vampire 查询
- **核心逻辑**（修复后）：
  - driving_hours 从 `drives.duration_min` 求和（Bug A 修复）
  - idle = asleep + offline + max(0, online - driving)
  - persona 判定：idle > 85% "闲得发慌"，driving/total > 30% "疲惫不堪"等
- **评估**：🟡
  - idle 阈值定得较宽（>85%）—— 日常上班族车辆白天都停，很容易 >85%
  - persona 文案对所有场景都输出，但**分界不合理**：比如 driving_hours=7.5 × idle=87%（你的数据），应该算"正常上班族"而不是"闲得发慌"
  - 改进：多维判定，考虑 trip_count、distance 等综合

---

### 30. `get_charging_vintage_data`
- **干什么**：单次充电详细参数（给 LLM 当"品鉴师"）
- **数据源**：`charging_processes` + 地址（修复后用 address_id JOIN）
- **核心逻辑**：查指定充电或最新充电，返回温度/SOC/地点等
- **评估**：🟢 纯数据展示，无复杂统计

---

### 31. `get_driver_profile`
- **干什么**：游戏化档案（等级/里程碑/彩蛋）
- **数据源**：`drives`（总里程）+ `charging_processes`（充电次数）
- **核心逻辑**：
  - 6 级：青铜 0 / 白银 10k / 黄金 50k / 王者 100k / 钻石 160k / 星耀 300k
  - 距离/充电里程碑字典硬编码
  - 160k-168k 彩蛋（质保过保）
- **评估**：🟢 纯游戏化设计，逻辑自洽
  - 小瑕疵：里程碑列表硬编码，加/删需要改代码；可移到配置

---

### 32. `check_daily_quest`
- **干什么**：今日随机任务（三选一）+ 当日进度
- **数据源**：`drives`（今日行程）
- **核心逻辑**：
  - 日期 MD5 哈希 mod 3 决定今日任务
  - 查今日驾驶数据判断进度
- **评估**：🟢 简单清晰
  - 小瑕疵：avg_wh_per_km 用 ideal_range 估算（当日充电少、数据不稳），可能误判
  - 3 个任务里 "trip_count >= 2" 和 "max_trip_km > 50" 对市区通勤日常容易达成，"eco_driver 150 Wh/km"偏难（冬天几乎不可能）—— 难度不均

---

### 33. `get_longest_trip_on_single_charge`
- **干什么**：单次充电最远行驶记录
- **数据源**：`drives` + `charging_processes`
- **核心逻辑**（修复后）：
  - 充电窗口 = 两次 charging 之间
  - 窗口内所有 drives.distance 求和
  - 只看闭环窗口（Bug #18 修复）
  - 取 SUM 最大的
- **评估**：🟢 修复后逻辑合理
  - 小瑕疵：`start_battery_pct` 取 `cp.end_battery_level`（充电结束时电量），`arrival_battery_pct` 取下次充电开始时电量。**中间可能有休眠掉电未计入**（vampire drain），所以 "battery_consumed_pct" 不完全等于"驾驶消耗"
  - 改进：扣除 vampire drain 部分

---

## 七、系统 & 历史（2）

### 34. `tesla_state_history`
- **干什么**：车辆状态（online/offline/asleep）转换历史
- **数据源**：`states`
- **核心逻辑**：按时间顺序列；按 state 累加总时长
- **评估**：🟢 直接展示状态流水，合理
  - 小瑕疵：TeslaMate 没 `driving` 子状态（Bug A 里发现），如果用户期望看"驾驶时长"这里看不到，要去 `drives` 表

---

### 35. `tesla_software_updates`
- **干什么**：OTA 升级历史
- **数据源**：`updates`
- **核心逻辑**：按 start_date DESC 列出
- **评估**：🟢 直接展示，没问题

---

## 📊 问题汇总（按优先级）

| 优先级 | 工具 | 问题 | 建议 |
|---|---|---|---|
| 🔴 高 | `tesla_driving_score` | 阈值硬编码（50 kW/130 km/h）对 Model 3P 日常驾驶过于严苛，评分严重失真 | 阈值可配置；结合车型/温度/道路类型 |
| 🟡 中 | `tesla_status` / `tesla_live` | 续航用配置 × 百分比，忽略电池衰减 | 优先读 `positions.ideal_battery_range_km` |
| 🟡 中 | `tesla_trips_by_category` | 分类器中文关键词缺失；home/work 跨城误判 | 加中文词典 + home/work 增加同城约束 |
| 🟡 中 | `tesla_location_history` | "count"不等于"时间"，口径不一致 | 改用 `MAX(date)-MIN(date)` 或间隔累加 |
| 🟡 中 | `tesla_battery_health` | 季节效应未校正，可能误算衰减 | 按年同比或温度分桶 |
| 🟡 中 | `tesla_top_destinations` | GPS 漂移导致同地被分多 address_id | 按坐标聚类或 geofence 聚合 |
| 🟡 中 | `tesla_savings` | 固定电价忽略家充 vs 超充成本差 | 优先用 `cp.cost` |
| 🟡 中 | `tesla_trip_cost` | 1.3 硬编码、无路径/天气因素 | 路径 API 或用户 hint |
| 🟡 中 | `generate_monthly_driving_report` | 能耗 penalty 阈值 150 Wh/km 太严格 | 按车型或用户分位数 |
| 🟡 中 | `get_vehicle_persona_status` | persona 阈值不合理（idle 85%） | 多维判定 |
| 🟡 中 | `tesla_monthly_summary` | 月份边界用 UTC 未转 USER_TZ | 与 #20 同步修 |
| 🟡 低 | `tesla_tpms_history` | 60 条原始采样，30天维度不足 | 按日聚合 |
| 🟡 低 | `tesla_trip_categories` | 只看最近 500 条，样本不代表长期 | 加时间参数 |
| 🟡 低 | `tesla_efficiency_by_temp` | 公制阈值仍按英制（4.4/15.6 等） | 公制改用整数阈值 |
| 🟡 低 | `tesla_tpms_status` | 文档 0.15 bar vs 代码 0.2 bar | 文档或代码二选一 |
| 🟡 低 | `get_longest_trip_on_single_charge` | 未扣除 vampire drain | 单独扣除 |
| 🟡 低 | `tesla_live` vs `tesla_status` | 70% 代码重复 | 合并或明确差异定位 |

---

## 🎯 总结

- **🟢 逻辑合理**：20 个工具
- **🟡 有瑕疵但能用**：14 个工具
- **🔴 应修复**：1 个（`tesla_driving_score`）

**核心特点**：
- **修复已完成的部分**（时区/LATERAL/vampire/能耗源等）都已经 🟢
- **剩下的 🟡 主要集中在业务规则层**（阈值、权重、关键词词典等），改动需要产品决策
- **`tesla_driving_score` 是唯一 🔴**：阈值体系对性能车用户不适用，建议优先处理
