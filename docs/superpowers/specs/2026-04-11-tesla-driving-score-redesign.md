# tesla_driving_score 函数重新设计

## 背景

原 `tesla_driving_score` 函数的参数不完整，只支持 `recent_n`、`monthly`、`yearly`，无法满足以下常见场景：
- 最近1天
- 最近1周
- 最近多个月（每月一行输出）

且原方案存在 bug：驾驶次数超过25次时评分归零（已修复）。

## 需求

| 调用场景 | 参数组合 |
|----------|----------|
| 最近N次驾驶 | `period="recent_n", n=N` |
| 最近N天 | `period="days", days=N` |
| 指定月份 | `period="monthly", year=Y, month=M` |
| 连续多个月（每月一行） | `period="months", year=Y, start_month=S, end_month=E` |

## 参数设计

```python
period: str           # "recent_n" | "days" | "monthly" | "months"
n: int | None = None      # 最近n次驾驶 (period="recent_n")
days: int | None = None   # 最近N天 (period="days")
year: int | None = None  # 年份 (period="monthly"/"months")
start_month: int | None = None  # 起始月份 (period="months")
end_month: int | None = None    # 结束月份 (period="months")
month: int | None = None    # 月份 (period="monthly")
```

## 调用示例

| 调用 | 含义 |
|------|------|
| `tesla_driving_score(period="recent_n", n=10)` | 最近10次驾驶 |
| `tesla_driving_score(period="days", days=1)` | 今天 |
| `tesla_driving_score(period="days", days=7)` | 最近7天 |
| `tesla_driving_score(period="monthly", year=2024, month=3)` | 2024年3月 |
| `tesla_driving_score(period="months", year=2024, start_month=1, end_month=3)` | 2024年1-3月，每月1行 |

## 时区处理

- **days 查询**：用 `USER_TZ` 的"今天 00:00:00"往前推 N 天
- **monthly/months 查询**：日期边界在 `USER_TZ` 中计算，存入DB前转UTC
- 代码复用项目中已有的 `USER_TZ` 和 datetime 处理模式

## 输出格式

每月/每个时间段一行，无汇总：

```
**Driving Score -- 2024-01**
驾驶安全评分: 92.0/100（平均每次驾驶扣0.8分）
总违章积分: 24分（30次驾驶）
违规事件: hard accel(2次), hard brake(1次)
驾驶次数: 30

**Driving Score -- 2024-02**
驾驶安全评分: 88.0/100（平均每次驾驶扣1.2分）
总违章积分: 36分（30次驾驶）
违规事件: hard accel(3次), high speed(1次)
驾驶次数: 30
```

## 评分算法（已修复）

```python
total_deduct = 累加所有扣分
avg_deduct = total_deduct / 驾驶次数
safety_score = max(0, 100 - avg_deduct * 10)
```

## 实现要点

1. 复用 `USER_TZ` 时区配置
2. 日期边界计算使用 `USER_TZ`，存入DB前转UTC
3. SQL 查询复用现有的 drives 表结构
4. 输出格式统一为中文
5. 无汇总，只有每个时间段的明细
