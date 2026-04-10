# Driver Gamification Tools — Design Spec

## 概述

新增三个 Tool，将驾驶数据游戏化：

| Tool | 功能 |
|------|------|
| `get_driver_profile` | 段位系统 + 里程碑成就 |
| `check_daily_quest` | 每日随机驾驶挑战 |
| `get_longest_trip_on_single_charge` | 单次充电极限续航记录 |

---

## Tool 1: `get_driver_profile`

### 数据库查询

```sql
-- 历史总里程
SELECT COALESCE(SUM(distance), 0) AS total_distance_km
FROM drives WHERE car_id = %s;

-- 历史总充电次数（已完成）
SELECT COUNT(*) AS total_charge_count
FROM charging_processes
WHERE car_id = %s AND end_date IS NOT NULL;
```

### 段位规则

| 里程范围 | 段位 |
|----------|------|
| < 10,000 km | 🥉 青铜试飞员 |
| 10,000 – 50,000 km | 🥈 白银巡航者 |
| 50,000 – 100,000 km | 🥇 黄金领航员 |
| 100,000 – 160,000 km | 👑 王者星舰长 |
| 160,000 – 300,000 km | 💎 钻石捍卫者 |
| > 300,000 km | ✨ 星耀传世神 |

### 里程里程碑节点

`[1万, 5万, 10万, 16万, 30万]` km

检查逻辑：如果 `total_distance_km >= 节点` 且 `差值 < 5%`，视为已解锁。

### 充电次数里程碑

`[50, 100, 500]` 次

### Easter Egg

若里程刚好跨过 160,000 km，追加特殊 milestone：
> 🎉 恭喜达成 16 万公里！您已正式脱离特斯拉电池质保新手保护区，真正的硬核生存模式开启！

### 输出 JSON

```json
{
  "current_rank": "👑 王者星舰长",
  "total_distance_km": 125300,
  "total_charges": 280,
  "milestones_unlocked": [
    "累计里程突破 10 万公里大关！",
    "您已成为百氪充电达人！"
  ],
  "next_milestone_hint": "距离【16万公里】质保期满挑战还差 34700 km，准备好迎接脱保的洗礼了吗？"
}
```

---

## Tool 2: `check_daily_quest`

### 任务池

| ID | 名称 | 描述 | 达标条件 |
|----|------|------|----------|
| eco_driver | 黄金右脚 | 今日所有行程平均能耗 < 150 Wh/km | avg_energy < 150 |
| explorer | 探索者 | 今日单次行程 > 50 km | max_single_trip > 50 |
| commuter | 勤劳小蜜蜂 | 今日行程 >= 2 次 | trip_count >= 2 |

### 任务选择逻辑

```python
# 用当天日期（北京时间）的哈希值来伪随机选任务
import hashlib
date_str = _utcnow().astimezone(USER_TZ).strftime("%Y-%m-%d")
quest_id = ["eco_driver", "explorer", "commuter"][
    int(hashlib.md5(date_str.encode()).hexdigest(), 16) % 3
]
```

### 数据库查询

```sql
SELECT
  SUM(distance) AS total_distance,
  SUM(energy_used) AS total_energy,
  COUNT(*) AS trip_count,
  MAX(distance) AS max_single_trip
FROM drives
WHERE car_id = %s
  AND start_date >= %s  -- 今天北京时间 00:00 转 UTC
  AND start_date < %s   -- 明天北京时间 00:00 转 UTC
  AND end_date IS NOT NULL;
```

能耗公式：`avg_wh_per_km = (SUM(energy_used) / SUM(distance)) * 1000`，分母为0时返回 None。

### 输出 JSON

```json
{
  "date": "2026-04-10",
  "quest_name": "黄金右脚",
  "quest_description": "今日所有行程平均能耗低于 150 Wh/km",
  "status": "已完成",
  "current_progress": "目前平均能耗 145 Wh/km",
  "target": "150 Wh/km"
}
```

`status` 枚举：`未开始`（今日无行程）/ `进行中`（有行程但未达标）/ `已完成`

---

## Tool 3: `get_longest_trip_on_single_charge`

### 核心 SQL（窗口函数）

```sql
WITH charge_windows AS (
  SELECT
    cp.id AS charge_id,
    cp.end_date AS charge_end,
    LEAD(cp.end_date) OVER (ORDER BY cp.start_date) AS next_charge_end,
    LEAD(cp.start_date) OVER (ORDER BY cp.start_date) AS next_charge_start,
    LEAD(cp.start_battery_level) OVER (ORDER BY cp.start_date) AS arrival_battery
  FROM charging_processes cp
  WHERE cp.car_id = %s AND cp.end_date IS NOT NULL
),
window_drives AS (
  SELECT
    cw.charge_id,
    cw.charge_end,
    cw.next_charge_start,
    cw.arrival_battery,
    d.distance,
    d.start_date
  FROM charge_windows cw
  JOIN drives d
    ON d.car_id = %s
   AND d.start_date >= cw.charge_end
   AND (cw.next_charge_start IS NULL OR d.start_date < cw.next_charge_start)
)
SELECT
  charge_id,
  charge_end,
  next_charge_start,
  arrival_battery,
  SUM(distance) AS total_distance_km,
  MIN(start_date) AS trip_start
FROM window_drives
GROUP BY charge_id, charge_end, next_charge_start, arrival_battery
ORDER BY total_distance_km DESC
LIMIT 1;
```

### 补充查询

根据上面的 `charge_id` 查询该次充电的 `end_battery_level`（出发电量）。

### 输出 JSON

```json
{
  "record_distance_km": 387.5,
  "start_time": "2026-03-15 08:23",
  "end_time": "2026-03-16 02:45",
  "start_battery_pct": 98,
  "arrival_battery_pct": 12,
  "battery_consumed_pct": 86,
  "efficiency_comment": "一次充电狂飙 387km，续航榨汁机实锤！"
}
```

`efficiency_comment` 规则：
- > 400 km: "一次充电狂飙 {distance}km，简直是续航榨汁机！"
- 300-400 km: "单次 {distance} km，稳稳的第一梯队！"
- 200-300 km: "跑了 {distance} km，中上表现，继续保持！"
- < 200 km: "单次 {distance} km，还有提升空间哦~"

---

## 放置位置

三个 Tool 都添加在 `tesla.py` 文件末尾，现有 `# -- Eco & Persona Tools --` 段落之后。新增段落标记：

```python
# -- Gamification Tools -------------------------------------------------------
```

---

## 依赖

- `_query()` / `_query_one()` — 现有 DB 工具
- `_utcnow()` — 现有 UTC 时间
- `USER_TZ` — 现有用户时区
- `CAR_ID` — 现有车辆 ID
- `json` — 现有 JSON 序列化
- `hashlib` — Python 标准库（md5）
