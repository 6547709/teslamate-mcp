# Driver Gamification Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add three new MCP tools to `tesla.py`: `get_driver_profile`, `check_daily_quest`, `get_longest_trip_on_single_charge`.

**Architecture:** All three tools are read-only database queries + Python game-logic post-processing. They live in `tesla.py` as async functions decorated with `@mcp.tool()`. Output is JSON strings via `json.dumps(..., ensure_ascii=False, indent=2)`.

**Tech Stack:** Python standard library (`json`, `hashlib`, `datetime`, `zoneinfo`), `psycopg2` (via existing `_query`/`_query_one` helpers), existing `USER_TZ`/`_utcnow()`/`CAR_ID` constants.

---

## File Map

- **Modify:** `tesla.py` — insert three new `@mcp.tool()` async functions before line 2910 (`# -- Entry point --`), and add `import hashlib` near the top if not already present.

---

## Task 1: Add `hashlib` import

**File:** `tesla.py:63-75` (imports section)

- [ ] **Step 1: Verify `hashlib` is not yet imported**

Run: `grep -n "^import hashlib" tesla.py`
Expected: no output (not imported yet)

- [ ] **Step 2: Add `import hashlib` after `import json`**

```python
import json
import hashlib
import logging
```

- [ ] **Step 3: Commit**

```bash
git add tesla.py && git commit -m "feat: add hashlib import for daily quest"
```

---

## Task 2: Implement `get_driver_profile`

**File:** `tesla.py` — insert new function before line 2910 (`# -- Entry point --`)

- [ ] **Step 1: Write the function**

```python
@mcp.tool()
async def get_driver_profile() -> str:
    """Get driver gamification profile -- rank, milestones, and Easter eggs.

    Returns the user's current driving rank, total stats, unlocked milestones,
    and hints for the next milestone. Easter egg triggers at 160,000 km.

    Returns JSON with: current_rank, total_distance_km, total_charges,
    milestones_unlocked (list), next_milestone_hint, and special_160k Easter egg.
    """
    _log.info(f"[TOOL] get_driver_profile called")

    # -- Query 1: total distance --
    drive_row = _query_one(
        "SELECT COALESCE(SUM(distance), 0) AS total_distance_km FROM drives WHERE car_id = %s",
        (CAR_ID,),
    )
    total_km = float(drive_row["total_distance_km"]) if drive_row else 0.0

    # -- Query 2: total charge count --
    charge_row = _query_one(
        "SELECT COUNT(*) AS total_charge_count FROM charging_processes WHERE car_id = %s AND end_date IS NOT NULL",
        (CAR_ID,),
    )
    total_charges = int(charge_row["total_charge_count"]) if charge_row else 0

    # -- Rank system --
    RANK_BRONZE       = ("🥉 青铜试飞员",     0)
    RANK_SILVER       = ("🥈 白银巡航者",     10_000)
    RANK_GOLD         = ("🥇 黄金领航员",    50_000)
    RANK_KING         = ("👑 王者星舰长",   100_000)
    RANK_DIAMOND      = ("💎 钻石捍卫者",   160_000)
    RANK_STAR         = ("✨ 星耀传世神",   300_000)

    ranks = [RANK_STAR, RANK_DIAMOND, RANK_KING, RANK_GOLD, RANK_SILVER, RANK_BRONZE]
    current_rank = RANK_BRONZE[0]
    for rank_name, threshold in ranks:
        if total_km >= threshold:
            current_rank = rank_name
            break

    # -- Milestone system --
    milestones_unlocked = []

    # Distance milestones
    DISTANCE_NODES = [1_000, 5_000, 10_000, 16_000, 30_000]
    DISTANCE_LABELS = {
        1_000:   "累计里程突破 1 千公里！",
        5_000:   "累计里程突破 5 千公里！",
        10_000:  "累计里程突破 1 万公里大关！",
        16_000:  "累计里程突破 16 万公里！质保期已满，真正的硬核模式开启！",
        30_000:  "累计里程突破 30 万公里！传奇级别！",
    }
    for node in DISTANCE_NODES:
        if total_km >= node * 10:  # stored in km, node is multiplied by 10
            label = DISTANCE_LABELS.get(node)
            if label and label not in milestones_unlocked:
                milestones_unlocked.append(label)

    # Charge milestones
    CHARGE_NODES = [50, 100, 500]
    CHARGE_LABELS = {
        50:  "您已成为五十氪充电达人！",
        100: "您已成为百氪充电达人！",
        500: "您已成为五百氪充电王者！",
    }
    for node in CHARGE_NODES:
        if total_charges >= node:
            label = CHARGE_LABELS.get(node)
            if label and label not in milestones_unlocked:
                milestones_unlocked.append(label)

    # -- Easter egg: 160,000 km --
    special_160k = None
    DISTANCE_NODE_160K = 160_000
    if DISTANCE_NODE_160K * 10 <= total_km < DISTANCE_NODE_160K * 10 * 1.05:
        special_160k = "🎉 恭喜达成 16 万公里！您已正式脱离特斯拉电池质保新手保护区，真正的硬核生存模式开启！"

    # -- Next milestone hint --
    next_node = None
    all_nodes = sorted(set(list(DISTANCE_NODES) * 10 + [r[1] for r in ranks if r[1] > 0]))
    for n in all_nodes:
        if n > total_km:
            next_node = n
            break
    next_milestone_hint = None
    if next_node:
        diff = next_node - total_km
        next_milestone_hint = f"距离【{next_node:,}公里】还差 {diff:,.0f} km，继续加油！"

    # -- Build result --
    result = {
        "current_rank": current_rank,
        "total_distance_km": round(total_km, 1),
        "total_charges": total_charges,
        "milestones_unlocked": milestones_unlocked,
        "next_milestone_hint": next_milestone_hint,
    }
    if special_160k:
        result["special_160k"] = special_160k

    return json.dumps(result, ensure_ascii=False, indent=2)
```

- [ ] **Step 2: Commit**

```bash
git add tesla.py && git commit -m "feat: add get_driver_profile tool"
```

---

## Task 3: Implement `check_daily_quest`

**File:** `tesla.py` — insert new function after `get_driver_profile`

- [ ] **Step 1: Write the function**

```python
@mcp.tool()
async def check_daily_quest() -> str:
    """Check today's daily driving quest and progress.

    Uses a deterministic hash of the current Beijing date to select one quest
    from the pool each day. Returns status: 未开始/进行中/已完成.

    Quest pool:
      - eco_driver (黄金右脚): avg energy < 150 Wh/km today
      - explorer (探索者): max single trip > 50 km today
      - commuter (勤劳小蜜蜂): trip count >= 2 today

    Returns JSON with: date, quest_name, quest_description, status,
    current_progress, target.
    """
    _log.info(f"[TOOL] check_daily_quest called")

    QUEST_POOL = {
        "eco_driver": ("黄金右脚", "今日所有行程平均能耗低于 150 Wh/km", "avg_wh_per_km"),
        "explorer": ("探索者", "今日单次行程超过 50 km", "max_trip_km"),
        "commuter": ("勤劳小蜜蜂", "今日行程次数 >= 2 次", "trip_count"),
    }

    # Select quest using date hash (Beijing timezone)
    today_str = _utcnow().astimezone(USER_TZ).strftime("%Y-%m-%d")
    quest_id = list(QUEST_POOL.keys())[
        int(hashlib.md5(today_str.encode()).hexdigest(), 16) % len(QUEST_POOL)
    ]
    quest_name, quest_desc, quest_key = QUEST_POOL[quest_id]

    # Build UTC datetime range for today in Beijing
    today_local = datetime.fromisoformat(today_str).replace(tzinfo=USER_TZ)
    tomorrow_local = today_local + timedelta(days=1)
    today_utc = today_local.astimezone(timezone.utc)
    tomorrow_utc = tomorrow_local.astimezone(timezone.utc)

    # Query today's drives
    rows = _query(
        """
        SELECT distance, energy_used
        FROM drives
        WHERE car_id = %s
          AND start_date >= %s
          AND start_date < %s
          AND end_date IS NOT NULL
        """,
        (CAR_ID, today_utc.isoformat(), tomorrow_utc.isoformat()),
    )

    trip_count = len(rows)
    total_distance = sum(float(r["distance"] or 0) for r in rows)
    total_energy = sum(float(r["energy_used"] or 0) for r in rows)

    # Compute metrics
    avg_wh_per_km = (total_energy / total_distance * 1000) if total_distance > 0 else None
    max_trip_km = max((float(r["distance"] or 0) for r in rows), default=0.0)

    # Evaluate quest
    if trip_count == 0:
        status = "未开始"
        progress = "今日暂无行程记录"
    elif quest_key == "avg_wh_per_km":
        if avg_wh_per_km is None:
            status = "未开始"
            progress = "今日暂无有效能耗数据"
        elif avg_wh_per_km < 150:
            status = "已完成"
            progress = f"目前平均能耗 {avg_wh_per_km:.0f} Wh/km ✅"
        else:
            status = "进行中"
            progress = f"目前平均能耗 {avg_wh_per_km:.0f} Wh/km（目标 < 150）"
    elif quest_key == "max_trip_km":
        if max_trip_km > 50:
            status = "已完成"
            progress = f"今日最长单次 {max_trip_km:.1f} km ✅"
        else:
            status = "进行中"
            progress = f"今日最长单次 {max_trip_km:.1f} km（目标 > 50 km）"
    else:  # commuter
        if trip_count >= 2:
            status = "已完成"
            progress = f"今日已完成 {trip_count} 次行程 ✅"
        else:
            status = "进行中"
            progress = f"今日已完成 {trip_count} 次行程（目标 >= 2）"

    result = {
        "date": today_str,
        "quest_name": quest_name,
        "quest_description": quest_desc,
        "status": status,
        "current_progress": progress,
        "target": "150 Wh/km" if quest_key == "avg_wh_per_km" else ("50 km" if quest_key == "max_trip_km" else "2 次行程"),
    }
    return json.dumps(result, ensure_ascii=False, indent=2)
```

- [ ] **Step 2: Commit**

```bash
git add tesla.py && git commit -m "feat: add check_daily_quest tool"
```

---

## Task 4: Implement `get_longest_trip_on_single_charge`

**File:** `tesla.py` — insert new function after `check_daily_quest`

- [ ] **Step 1: Write the function**

```python
@mcp.tool()
async def get_longest_trip_on_single_charge() -> str:
    """Find the longest distance driven between two consecutive charges.

    Uses window functions on charging_processes to define charge windows,
    then sums drives within each window to find the record.

    Returns JSON with: record_distance_km, start_time, end_time,
    start_battery_pct, arrival_battery_pct, battery_consumed_pct,
    efficiency_comment.
    """
    _log.info(f"[TOOL] get_longest_trip_on_single_charge called")

    row = _query_one(
        """
        WITH charge_windows AS (
            SELECT
                cp.id AS charge_id,
                cp.end_date AS charge_end,
                cp.end_battery_level AS start_battery,
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
                cw.start_battery,
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
            start_battery,
            arrival_battery,
            SUM(distance) AS total_distance_km,
            MIN(start_date) AS trip_start
        FROM window_drives
        GROUP BY charge_id, charge_end, next_charge_start, start_battery, arrival_battery
        ORDER BY total_distance_km DESC
        LIMIT 1
        """,
        (CAR_ID, CAR_ID),
    )

    if not row or not row["total_distance_km"]:
        return json.dumps({"error": "No complete charge cycles found"}, ensure_ascii=False)

    distance = float(row["total_distance_km"])
    start_time = _format_dt(row["charge_end"])
    end_time = _format_dt(row["next_charge_start"]) if row["next_charge_start"] else "至今"
    start_battery = row["start_battery"]
    arrival_battery = row["arrival_battery"]
    battery_consumed = (start_battery or 0) - (arrival_battery or 0) if start_battery and arrival_battery else None

    if distance > 400:
        comment = f"一次充电狂飙 {distance:.1f}km，简直是续航榨汁机！"
    elif distance > 300:
        comment = f"单次 {distance:.1f} km，稳稳的第一梯队！"
    elif distance > 200:
        comment = f"跑了 {distance:.1f} km，中上表现，继续保持！"
    else:
        comment = f"单次 {distance:.1f} km，还有提升空间哦~"

    result = {
        "record_distance_km": round(distance, 1),
        "start_time": start_time,
        "end_time": end_time,
        "start_battery_pct": start_battery,
        "arrival_battery_pct": arrival_battery,
        "battery_consumed_pct": round(battery_consumed, 1) if battery_consumed else None,
        "efficiency_comment": comment,
    }
    return json.dumps(result, ensure_ascii=False, indent=2)
```

- [ ] **Step 2: Commit**

```bash
git add tesla.py && git commit -m "feat: add get_longest_trip_on_single_charge tool"
```

---

## Task 5: Update README documentation

**File:** `README.md` and `README_zh.md` — add the three new tools to the tool list

- [ ] **Step 1: Add to README.md tool list (after `generate_monthly_driving_report`)**

```markdown
  get_driver_profile          -- Driver rank, milestones, Easter eggs
  check_daily_quest           -- Today's random driving challenge
  get_longest_trip_on_single_charge -- Longest distance between two charges
```

- [ ] **Step 2: Commit**

```bash
git add README.md && git commit -m "docs: add new gamification tools to README"
```

---

## Task 6: Tag and push

- [ ] **Step 1: Create new tag v0.11.9**

```bash
git tag v0.11.9
```

- [ ] **Step 2: Push to GitHub**

```bash
git push origin main --tags
```

---

## Self-Review Checklist

- [ ] All three tools have correct `@mcp.tool()` decorators
- [ ] All DB queries use `CAR_ID` as the bound parameter
- [ ] `get_driver_profile` — distance thresholds match spec (1万=10000, 5万=50000, 10万=100000, 16万=160000, 30万=300000)
- [ ] `check_daily_quest` — uses `USER_TZ` for date hash, uses `today_utc`/`tomorrow_utc` for DB query range
- [ ] `check_daily_quest` — `energy_used` column (not `energy`) for drives table
- [ ] `get_longest_trip_on_single_charge` — window function `LEAD` on `start_date` (not `end_date`) is correct
- [ ] All functions return `json.dumps(..., ensure_ascii=False, indent=2)`
- [ ] No placeholder code, TODOs, or vague descriptions
- [ ] Each task has its own commit
