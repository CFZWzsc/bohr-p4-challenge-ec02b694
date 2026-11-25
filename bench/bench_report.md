# 实验参数优化基准报告

协议版本：`optimization-bench-v1`。本报告由 `bench/run_bench.py` 生成，内容只依赖案例、金标准与两次运行输出。

## 公平协议

- 案例：`bench/cases/*.json`，合成且自洽；真实响应函数写在案例 `notes` 与金标准 `notes` 中，形状为抛物面，最优在可行域角点。
- 金标准：`bench/gold/*.json`，由真实响应函数直接给出；脚本启动时断言函数在金标准最优点上的取值等于金标准响应值，防止金标准漂移。
- 技能侧：运行 `scripts/run_skill.py`，取其 `recommendation.recommended_values` 与 `budget.planned_runs`。
- 基线：直接取历史观测中响应最好的那一点（maximize 取最大、minimize 取最小），并按全网格点数排期。
- 每个案例独立运行一次，运行目录为临时目录并在结束后删除；不使用网络、不使用随机数。

## 指标定义

- L1 距离：推荐点与真实最优在各参数上绝对差之和（单位与参数一致，跨参数直接相加）。
- 真实响应：把推荐点代入案例声明的响应函数得到的值；与最优值之差 `response_gap` 以“变差幅度”计，非负表示劣于最优。
- 预算内运行数：计划运行数在同时满足 `planned_runs*成本 <= 预算上限` 与 `planned_runs <= max_runs` 时计入，否则记 0。
- 基线排期按参数域的完整网格点数计算，代表“不核算预算、直接扫全域”的朴素做法。

## 逐例结果

### `bench-corner-max-yield`

- 目标方向：最大化；真实最优 {"residence_time_min": 40, "temperature_c": 60}，最优响应 88.0。

| 方法 | 推荐点 | L1 距离 | 真实响应 | 与最优之差 | 计划运行数 | 计划成本 | 预算内 | 预算内运行数 |
|---|---|---|---|---|---|---|---|---|
| 技能 | {"residence_time_min": 40.0, "temperature_c": 60.0} | 0.0 | 88.0 | 0.0 | 20 | 400.0 | 是 | 20 |
| 基线 | {"residence_time_min": 30, "temperature_c": 60} | 10.0 | 84.0 | 4.0 | 49 | 980.0 | 否 | 0 |

- 技能 `status`：`success`，模型 `fitted`，推荐来源 `linear_surrogate`。
- 增益：L1 减少 10.0，与最优的响应差缩小 4.0，预算内运行数增加 20。

### `bench-corner-min-impurity`

- 目标方向：最小化；真实最优 {"catalyst_loading_wt": 0.5, "reaction_time_min": 20}，最优响应 25.0。

| 方法 | 推荐点 | L1 距离 | 真实响应 | 与最优之差 | 计划运行数 | 计划成本 | 预算内 | 预算内运行数 |
|---|---|---|---|---|---|---|---|---|
| 技能 | {"catalyst_loading_wt": 0.5, "reaction_time_min": 20.0} | 0.0 | 25.0 | 0.0 | 15 | 450.0 | 是 | 15 |
| 基线 | {"catalyst_loading_wt": 1.0, "reaction_time_min": 30} | 10.5 | 29.25 | 4.25 | 25 | 750.0 | 否 | 0 |

- 技能 `status`：`success`，模型 `fitted`，推荐来源 `linear_surrogate`。
- 增益：L1 减少 10.5，与最优的响应差缩小 4.25，预算内运行数增加 15。

## 汇总

| 指标 | 技能 | 基线 |
|---|---|---|
| L1 距离合计 | 0.0 | 20.5 |
| 与最优的响应差合计 | 0.0 | 8.25 |
| 预算内运行数合计 | 35 | 0 |
| 全部案例严格更优 | true | - |

## 复现

```bash
python bench/run_bench.py
```

脚本重写 `bench/bench_metrics.json` 与 `bench/bench_report.md`；同一输入重复运行字节一致。
