# Quickstart — bounded parameter recommendation

Python 3.10+ standard library only; no network access.

## 1. Run the bundled demo

```bash
python scripts/run_skill.py --case examples/demo-case/case.json --out result.json
```

Expected on the demo case (byte-identical across runs):

- `status` = `success`
- `recommendation.recommended_values` = `{"temperature_c": 40.0, "residence_time_min": 30.0}`
- `recommendation.predicted_response` = 66.78, `predicted_margin` = 2.33
- `recommendation.recommended_values_source` = `linear_surrogate` (a prediction, not a measurement)
- `budget.planned_cost` = `planned_runs * cost_per_run`; when the case omits
  `cost_per_run`, `planned_cost` is `null` instead of a guessed number

## 2. Your own case

```json
{
  "case_id": "my-optimisation",
  "parameters": [
    {"name": "temperature_c", "min": 20, "max": 60, "step": 5, "unit": "C"},
    {"name": "residence_time_min", "min": 10, "max": 60, "step": 10, "unit": "min"}
  ],
  "constraints": [{"parameter": "temperature_c", "max": 50}],
  "objective": {"name": "yield_pct", "direction": "maximize", "unit": "%"},
  "observations": [
    {"temperature_c": 20, "residence_time_min": 10, "yield_pct": 41.2},
    {"temperature_c": 40, "residence_time_min": 30, "yield_pct": 66.8}
  ],
  "budget_limit": 500,
  "cost_per_run": 25
}
```

```bash
python scripts/run_skill.py --case case.json --out result.json
```

## 3. Behaviour you can rely on

- With enough observations the linear surrogate is fitted; `stop_rule` states
  when the margin is wide enough to stop.
- With too few observations (fewer than the model needs) the script returns
  `recommended_values` = the best *observed feasible* point with
  `recommended_values_source = "observed"`, plus exploration anchors — it never
  invents a predicted optimum.
- Constraints that remove every grid point yield `status = "partial"` with
  `no_feasible_solution` in `notes`, not a silent clip.
- Missing input still writes `result.json` and exits 0.
