# 实验参数优化基准（bench）

本目录用两个合成但自洽的案例，对比技能推荐点与“直接取观测最优”基线在接近真实最优的程度、真实响应差距与预算内排期上的差异。目的是给出可复核的过程证据，而不是评分声明。

## 公平协议

1. 每个案例只运行一次 `scripts/run_skill.py`，输出写入临时目录，运行结束后删除。
2. 真实响应函数在案例 `notes` 与金标准 `notes` 中以公式写明；基准脚本内置同一函数，并在启动时断言 `f(金标准最优点) == 金标准响应值`，防止金标准与函数漂移。
3. 金标准只由真实响应函数给出，不取自技能的预测值；技能只读取 `recommendation.recommended_values` 与 `budget.planned_runs`。
4. 基线只读案例的 `observations`，不使用技能输出。
5. 两侧都按案例给出的 `budget.cost_per_run`、`budget.limit`、`budget.max_runs` 计算排期，不额外假设成本。

## 基线定义

基线 = 直接取历史观测中响应最好的那一点：

- `direction = maximize` 时取 `yield_pct` 最大的观测行；
- `direction = minimize` 时取 `impurity_ppm` 最小的观测行；
- 排期按参数域完整网格的点数（`min/max/step` 展开）乘以单次成本计算，代表“不核算预算、直接扫全域”的朴素做法。

两例都安排了一个含偏大噪声的观测点，使“取观测最优”落在真实次优点上。

## 指标定义

| 指标 | 定义 |
|---|---|
| `l1_distance` | 推荐点与真实最优在各参数上绝对差之和（跨参数直接相加，单位随参数） |
| `true_response` | 推荐点代入真实响应函数的值 |
| `response_gap` | 变差幅度：maximize 为 `最优值 - 推荐点值`，minimize 为 `推荐点值 - 最优值`；0 表示达到最优 |
| `planned_runs` | 技能取 `budget.planned_runs`；基线取完整网格点数 |
| `planned_cost` | `planned_runs * cost_per_run` |
| `within_budget` | 成本不超过预算上限，且运行数不超过 `max_runs` |
| `runs_within_budget` | 上述条件同时满足时等于 `planned_runs`，否则记 0 |
| `skill_strictly_better` | L1 距离与 `response_gap` 均严格更小 |

## 复现

在包根目录执行：

```bash
python bench/run_bench.py
```

脚本以标准库实现，通过子进程调用 `scripts/run_skill.py`（环境变量 `PYTHONDONTWRITEBYTECODE=1`、`PYTHONHASHSEED=0`），随后写入：

- `bench/bench_metrics.json`：`indent=2`、`sort_keys=True`，无时间戳与绝对路径；
- `bench/bench_report.md`：协议说明与逐例表格。

同一输入重复运行，两份文件字节一致。

## 已知边界

- 案例完全合成；真实响应是抛物面，最优恰在可行域角点，因此线性代理模型的正确性依赖“响应在观测覆盖区内单调”这一设定。
- 噪声只注入到一个观测点，其余观测仅含舍入误差；没有模拟多噪声源、离群点聚集或缺失观测。
- L1 距离把不同量纲的参数差直接相加，只用于同一案例内比较，不跨案例解释。
- 基线只覆盖“取观测最优”这一种朴素策略，不覆盖“取中心点”“取随机点”等其他做法。
- 技能的输出是“代理模型预测的最优”，不是实测最优；本基准比较的是与真实函数的距离，不对真实实验的可达性作保证。
- `max_runs` 与预算在本基准中按同时满足处理；只放宽其中一条会改变 `runs_within_budget`。
