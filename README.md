# 有界实验参数优化建议（包说明）

在有限参数域、设备量程与预算内，给出参数建议取值、可行区间、响应口径、搜索策略与停止判据。以下说明输入、口径、输出与限制，均对应 `SKILL.md` 与 `scripts/run_skill.py` 的实际行为。

## 输入字段

| 字段 | 含义 | 必需 |
|---|---|---|
| `case_id` | 案例标识，原样回填 | 是 |
| `output_contract` | 需要回填的输出键及其类型 | 是 |
| `parameters[]` | 参数名、`min`/`max`/`step` 或 `values`、`unit`；展开为有限候选集 | 是 |
| `objectives[]` | 目标名、`unit`、`direction`（`maximize`/`minimize`）；缺方向时默认 `maximize` 并记入不确定性 | 否 |
| `observations[]` | 每行含参数列与响应列的历史观测 | 否 |
| `budget` | `cost_per_run`、`limit`、`max_runs` 或同义键 | 否 |
| `constraints[]` | 参数上/下界、算符阈值、禁用组合 | 否 |
| `notes` | 背景说明；若写明真实响应公式，仅供人类复核，脚本不解析公式 | 否 |

字段缺失不会被补造：无参数域时状态为 `insufficient_input`；观测少于 3 条时不拟合，只给探索点。

## 优化口径

1. 参数域展开：按 `min`/`max`/`step` 等距取点（步长缺失取 5 点），或直接用 `values`；越界值不进入候选集，候选上限 20000，超限改为确定性分层抽样并记录。
2. 约束裁剪：逐条输出保留/剔除后的候选数；全部剔除时给 `no_feasible_solution`，不强行推荐。
3. 观测建模：观测数 ≥ 3 时用带截距的多元线性最小二乘拟合，输出系数、残差标准差、`R²` 与样本数；模型仅作代理，不冒充机理模型。
4. 推荐：只在可行候选上预测，按目标方向排序，取预测最优；同时给出可行区间与次优点的预测差值（`predicted_margin`）。
5. 停止规则：预测优势需同时超过“预测值的 5%”和残差标准差，且推荐点在观测凸包内；否则建议补一次确认运行。
6. 排期：`planned_runs` 由搜索策略给出（候选数超过 `max_runs` 时按序贯轮次分配），`planned_cost = planned_runs * cost_per_run`。

## 阈值与约束

- 可行域：推荐值必须落在参数域与约束的交集内；越界不推荐。
- 预算：`planned_cost <= limit` 时 `budget.within_budget = true`，否则为 `false` 且 `status = partial`。
- 通量：`planned_runs > max_runs` 时切换为序贯设计，并在轮次表中给出每轮点数。
- 拟合门槛：观测 ≥ 3 条且设计矩阵非奇异才给出 `fitted`；否则推荐回退为“最优观测点”，并注明这不是预测最优。
- 方向未声明、约束无法应用、候选被截断时状态为 `partial`，并在 `uncertainty` 中逐条说明。

## 输出字段

`result.json` 顶层：

| 字段 | 含义 |
|---|---|
| `case_id` / `status` | 案例标识与状态（`success` / `partial` / `insufficient_input` / `failed`） |
| `output_contract` 各键 | 与内部载荷同名则填真实值，否则 `null` 并在 `contract_notes` 说明 |
| `parameter_domains` | 每个参数的展开值、来源与是否无界 |
| `constraints` | 已应用/未应用约束及裁剪说明 |
| `feasible_space` | 各参数可用值、候选数、名义组合数、是否截断 |
| `observations` | 观测总数、目标名、可用于拟合的行数 |
| `model` | 拟合状态、系数、残差标准差、`R²` |
| `recommendation` | 推荐值、来源（代理模型或观测）、预测响应、次优差值、可行区间、停止规则 |
| `search_strategy` | 模式（全网格/序贯）、初始点、每轮点数、停止判据 |
| `budget` | 单次成本、上限、轮数、总成本、是否超预算及算术说明 |
| `risks` / `validation` | 风险与自检项 |
| `result` | 上述内容的完整载荷 |
| `evidence` | 输入文件名与哈希、命中键路径、规则版本 |
| `uncertainty` / `errors` / `stats` / `contract_notes` | 不确定项、真实错误、计数汇总、未映射字段说明 |

同目录还会写出 `report.md`、`validation.json`、`provenance.json`（人类可读报告、自检结果、输入哈希）。

## 依赖与限制

- 依赖：Python 3.8+，仅标准库；不联网、不读私有路径。
- 线性模型只是代理，不替代机理模型，也不把预测最优写成“实验已验证的最优”。
- 不生成供应商报价、设备真实量程或安全阈值；这些只能来自输入。
- 不做外推保证：推荐点落在观测覆盖区外时，只能作为待验证假设。
- 案例与示例均为合成数据，响应值为构造值，不代表真实工艺。

## 单次运行

在包根目录执行：

```bash
python scripts/run_skill.py --case examples/demo-case/case.json --out ./demo-output/result.json --work ./demo-output/work
```

一次运行即产出完整交付物，不存在第二阶段；同一输入重复运行字节一致。

## 复核与基准

`bench/` 内含两个“最优在角点、含一个偏大噪声观测”的合成案例、金标准、朴素基线对比脚本与协议说明；`templates/optimization_checklist.md` 提供可直接复用的优化建议复核清单。
