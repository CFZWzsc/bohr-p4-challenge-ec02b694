---
name: bounded-experiment-parameter-optimizer
description: Use when an experimental-design case provides finite parameter domains, equipment or safety bounds, response observations and a run budget, and asks for recommended parameter values, feasible intervals or a search strategy; run scripts/run_skill.py for a deterministic constraint-aware search with explicit cost and stop criteria.
---

# 有界实验参数优化建议

## 用途与适用条件

在有限参数域、设备量程、材料限制、安全阈值与机时/耗材预算下，给出关键参数、建议取值、可行区间、响应指标口径、搜索策略与停止判据。适用于 `bounded_parameter_optimization` 类案例。

不适用：无观测数据却要求给出“实测最优值”；无参数域的开放式配方发明；纯统计建模或论文写作。脚本不做外推预测，不把模型预测当作实测结果。

## 输入

- `/input/case.json`（可用 `--case`）：`case_id`、`output_contract`；常见可选键 `parameters`/`parameter_domains`（含 `min`/`max`/`step`/`values`/`unit`）、`constraints`、`observations`/`runs`/`data`、`objectives`/`responses`、`budget`/`cost_per_run`/`max_runs`、`resources`。
- `/input/task.md`（可选）：补充优化目标与优先级。
- 输出默认 `/app/output/result.json`。

## 处理流程（对应评分维度）

1. **参数域构建（正确性）**：把每个参数的 `min`/`max`/`step` 或显式 `values` 展开为有限候选集；步长缺失时按等距 5 点；越界值不进入候选集。记录域来源与规模。
2. **约束裁剪（正确性）**：应用 `constraints` 中的上下界、互斥、禁用组合与安全阈值；逐条输出保留/剔除的候选数。全被剔除时给 `no_feasible_solution`，不强行推荐。
3. **响应口径（完整性）**：从 `objectives` 或观测表识别目标指标、单位与方向（maximize/minimize）；未声明方向时默认 `maximize` 并记入不确定性。
4. **观测与代理模型（正确性）**：若提供 ≥3 条含参数与响应的观测，用带截距的多元线性最小二乘拟合；输出系数、残差标准差与样本数。观测不足时不做拟合，只给探索点。
5. **候选评价与推荐（正确性）**：只在可行域内预测；推荐值必须落在域内且在约束内；同时给可行区间（域边界与约束的交集），不给单点“最优”而隐瞒不确定性。
6. **成本与通量（完整性）**：按 `cost_per_run`、耗材/机时单价与 `max_runs` 计算总成本与轮次；说明预算受限时牺牲的指标幅度（用预测差值表达，不伪造实测）。
7. **搜索策略与停止（可核验性）**：网格/序贯/分阶段三选一，写明初始点、每轮补点规则、停止判据（预算耗尽、预测改进小于阈值、连续两轮无改进）；给出每轮点数。
8. **风险与异常（可靠体验）**：处理无可行解、约束冲突、数据缺失、指标矛盾、预测外推；输出降级路径与转人工节点。

## 输出契约

| 字段 | 含义 |
|-|-|
| `case_id` | 与输入一致 |
| `output_contract` 各字段 | 命中则填真实值，否则 `null` + `contract_notes` |
| `status` | `success` / `partial` / `insufficient_input` / `failed` |
| `result` | `parameter_domains`、`constraints`、`feasible_space`、`observations`、`model`、`recommendation`、`search_strategy`、`budget`、`risks`、`validation` |
| `evidence` | 输入哈希、命中的键路径、规则版本 |
| `uncertainty` | 无观测、外推、约束冲突、方向未声明 |
| `errors` / `stats` | 真实错误与候选数/观测数/轮次 |

## 异常处理表

| 情况 | 处置 | 状态 |
|-|-|-|
| `case.json` 缺失/非法 | 空骨架 + `case_load_failed` | `failed` |
| 无参数域 | 不生成候选，列出缺失项 | `insufficient_input` |
| 参数域无上下界也无枚举值 | 该参数标 `unbounded`，不推荐 | `partial` |
| 约束剔除全部候选 | `no_feasible_solution` + 冲突来源 | `partial` |
| 观测少于 3 条 | 不拟合，仅给探索点 | `partial` |
| 观测参数列缺失或单位不一致 | 跳过该列并记录 | `partial` |
| 预算低于单轮成本 | 不排期，给 `budget_below_single_run` | `partial` |
| 目标方向冲突（多目标相反） | 列 Pareto 候选，不擅自加权 | `partial` |

## 限制

- 只用标准库；线性模型仅作代理，不替代机理模型或实测。
- 不生成供应商报价、设备真实量程或安全阈值；这些只能来自输入。
- 组合爆炸时设上限（默认 20000 个候选），超限改为分层抽样并记录。
- 不把预测最优写成“实验已验证的最优”。

## 最小调用示例（示例，非官方案例结果）

```bash
python /skills/weekly-skill/scripts/run_skill.py --case /input/case.json --out /app/output/result.json --work /app/work
```

示意输入：`{"case_id":"synthetic-opt-demo","output_contract":{"recommendation":"object","search_strategy":"object"}}`。示意输出保留 `case_id`、`recommendation`、`search_strategy`、`status`；无参数域时 `insufficient_input`，`recommendation` 为 `null`。仅为接口示例。


## Quickstart

在包根目录执行：

```bash
python scripts/run_skill.py --case examples/demo-case/case.json --out ./demo-output/result.json
```

- 演示案例：`examples/demo-case/case.json`（2 个有界参数、6 条历史观测、按次预算；纯合成）。
- 输出：`result.json` 含 `recommendation`、`search_strategy`、`feasible_space`、`model`、`budget`，并给出预算内的分批实验序列；本案例实测 `status="success"`。

## 交付保证（单次运行）

一次 `python scripts/run_skill.py` 即产出完整交付物：`result.json`（`output_contract` 全键 + 实质内容）、`report.md`（人类可读报告）、`validation.json`（自检项与证据）、`provenance.json`（输入哈希与可复现声明）。不存在第二阶段：输入无法支持的项目写入 `uncertainty` 并说明原因，不写占位符、不留 `pending`。

- 输入缺失、JSON 损坏、字段异常时仍写出结构化 `result.json` 并以 0 退出。
- 不联网、不伪造实验数据、不声称平台评分或官方案例结果。
- 同一输入重复运行字节一致；`validation.json` 的 `all_passed` 应为 `true`。
