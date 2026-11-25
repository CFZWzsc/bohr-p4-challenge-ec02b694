#!/usr/bin/env python3
"""Deterministic benchmark for the bounded-parameter optimisation skill.

Compares the skill recommendation with a naive "best observed point" baseline
on two synthetic cases whose true response surface peaks at a domain corner.
Standard library only: no network, no timestamps, no absolute paths.
"""

import json
import os
import subprocess
import sys
import tempfile

BENCH_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BENCH_DIR)
CASE_DIR = os.path.join(BENCH_DIR, "cases")
GOLD_DIR = os.path.join(BENCH_DIR, "gold")
SKILL = os.path.join(ROOT, "scripts", "run_skill.py")
PROTOCOL = "optimization-bench-v1"


def response_yield(point):
    """yield_pct = 88 - 0.05*(T-60)^2 - 0.04*(t-40)^2 (formula stated in the case notes)."""
    return (88.0 - 0.05 * (point["temperature_c"] - 60.0) ** 2
            - 0.04 * (point["residence_time_min"] - 40.0) ** 2)


def response_impurity(point):
    """impurity_ppm = 25 + 5*(x-0.5)^2 + 0.03*(t-20)^2 (formula stated in the case notes)."""
    return (25.0 + 5.0 * (point["catalyst_loading_wt"] - 0.5) ** 2
            + 0.03 * (point["reaction_time_min"] - 20.0) ** 2)


RESPONSE = {
    "bench-corner-max-yield": response_yield,
    "bench-corner-min-impurity": response_impurity,
}


def load_json(path):
    with open(path, "r", encoding="utf-8-sig") as fh:
        return json.load(fh)


def round6(value):
    if value is None:
        return None
    return round(float(value), 6)


def run_skill(case_path):
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONHASHSEED"] = "0"
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "result.json")
        work = os.path.join(tmp, "work")
        proc = subprocess.run(
            [sys.executable, SKILL, "--case", case_path, "--out", out, "--work", work],
            cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        if proc.returncode != 0 or not os.path.isfile(out):
            raise RuntimeError("skill run failed for %s (exit %d): %s"
                               % (os.path.basename(case_path), proc.returncode, proc.stderr.strip()[:400]))
        return load_json(out)


def grid_size(case):
    total = 1
    for param in case.get("parameters") or []:
        low, high, step = param.get("min"), param.get("max"), param.get("step")
        if low is None or high is None or not step:
            raise RuntimeError("case parameter lacks min/max/step: %s" % param.get("name"))
        total *= int(round((high - low) / step)) + 1
    return total


def observed_best(case):
    """Naive baseline: take the single best measured observation."""
    objective = (case.get("objectives") or [{}])[0]
    name = objective["name"]
    maximize = objective.get("direction") != "minimize"
    best = None
    for row in case.get("observations") or []:
        if name not in row:
            continue
        if best is None or (row[name] > best[name] if maximize else row[name] < best[name]):
            best = row
    if best is None:
        raise RuntimeError("no observation carries the objective: %s" % name)
    values = {param["name"]: best[param["name"]] for param in case.get("parameters") or []}
    return {"values": values, "observed_response": best[name]}


def l1_distance(values, optimum):
    return round6(sum(abs(float(values[key]) - float(optimum[key])) for key in optimum))


def score(values, case, gold, response_fn):
    optimum = gold["optimum"]
    best_true = gold["true_response_at_optimum"]
    true_value = round6(response_fn(values))
    if case.get("objectives", [{}])[0].get("direction") == "minimize":
        gap = round6(true_value - best_true)
    else:
        gap = round6(best_true - true_value)
    return {
        "recommended_values": values,
        "l1_distance": l1_distance(values, optimum),
        "true_response": true_value,
        "response_gap": gap,
    }


def budget_block(runs, cost_per_run, limit, max_runs):
    planned_cost = round6(runs * cost_per_run) if cost_per_run is not None else None
    within = planned_cost is not None and limit is not None and planned_cost <= limit
    if max_runs is not None and runs > max_runs:
        within = False
    return {
        "planned_runs": runs,
        "planned_cost": planned_cost,
        "within_budget": within,
        "runs_within_budget": runs if within else 0,
    }


def benchmark_case(case_path, gold_path):
    case = load_json(case_path)
    gold = load_json(gold_path)
    case_id = case.get("case_id")
    if case_id != gold.get("case_id"):
        raise RuntimeError("case/gold id mismatch: %s" % os.path.basename(case_path))
    response_fn = RESPONSE.get(case_id)
    if response_fn is None:
        raise RuntimeError("no response function registered for %s" % case_id)

    # Guard: the published gold optimum must reproduce the published gold value.
    if abs(response_fn(gold["optimum"]) - gold["true_response_at_optimum"]) > 1e-9:
        raise RuntimeError("gold optimum/value mismatch for %s" % case_id)

    result = run_skill(case_path)
    payload = result.get("result") or {}
    recommendation = payload.get("recommendation") or {}
    skill_values = recommendation.get("recommended_values")
    if not isinstance(skill_values, dict) or not skill_values:
        raise RuntimeError("skill produced no recommendation for %s" % case_id)

    budget = case.get("budget") or {}
    cost_per_run = budget.get("cost_per_run")
    limit = budget.get("limit")
    max_runs = budget.get("max_runs")

    skill_runs = (payload.get("budget") or {}).get("planned_runs")
    if skill_runs is None:
        skill_runs = sum(round_info.get("points", 0)
                         for round_info in (payload.get("search_strategy") or {}).get("rounds") or [])

    skill_metrics = score(skill_values, case, gold, response_fn)
    skill_metrics["status"] = result.get("status")
    skill_metrics["model_status"] = (payload.get("model") or {}).get("status")
    skill_metrics.update(budget_block(int(skill_runs), cost_per_run, limit, max_runs))
    skill_metrics["source"] = recommendation.get("recommended_values_source")

    baseline_point = observed_best(case)
    baseline_metrics = score(baseline_point["values"], case, gold, response_fn)
    baseline_metrics["observed_response"] = round6(baseline_point["observed_response"])
    baseline_metrics["status"] = "not_applicable"
    baseline_metrics.update(budget_block(grid_size(case), cost_per_run, limit, max_runs))
    baseline_metrics["source"] = "best_observed"

    gain = {
        "l1_improvement": round6(baseline_metrics["l1_distance"] - skill_metrics["l1_distance"]),
        "response_gap_improvement": round6(baseline_metrics["response_gap"] - skill_metrics["response_gap"]),
        "runs_within_budget_delta": skill_metrics["runs_within_budget"] - baseline_metrics["runs_within_budget"],
        "skill_strictly_better": (
            skill_metrics["l1_distance"] < baseline_metrics["l1_distance"]
            and skill_metrics["response_gap"] < baseline_metrics["response_gap"]
        ),
    }
    return {
        "case_id": case_id,
        "case_file": "bench/cases/" + os.path.basename(case_path),
        "gold_file": "bench/gold/" + os.path.basename(gold_path),
        "gold": {
            "optimum": gold["optimum"],
            "true_response_at_optimum": gold["true_response_at_optimum"],
            "direction": case["objectives"][0].get("direction"),
        },
        "skill": skill_metrics,
        "baseline": baseline_metrics,
        "gain": gain,
    }


def render_report(payload):
    lines = []
    lines.append("# 实验参数优化基准报告")
    lines.append("")
    lines.append("协议版本：`%s`。本报告由 `bench/run_bench.py` 生成，内容只依赖案例、金标准与两次运行输出。" % PROTOCOL)
    lines.append("")
    lines.append("## 公平协议")
    lines.append("")
    lines.append("- 案例：`bench/cases/*.json`，合成且自洽；真实响应函数写在案例 `notes` 与金标准 `notes` 中，形状为抛物面，最优在可行域角点。")
    lines.append("- 金标准：`bench/gold/*.json`，由真实响应函数直接给出；脚本启动时断言函数在金标准最优点上的取值等于金标准响应值，防止金标准漂移。")
    lines.append("- 技能侧：运行 `scripts/run_skill.py`，取其 `recommendation.recommended_values` 与 `budget.planned_runs`。")
    lines.append("- 基线：直接取历史观测中响应最好的那一点（maximize 取最大、minimize 取最小），并按全网格点数排期。")
    lines.append("- 每个案例独立运行一次，运行目录为临时目录并在结束后删除；不使用网络、不使用随机数。")
    lines.append("")
    lines.append("## 指标定义")
    lines.append("")
    lines.append("- L1 距离：推荐点与真实最优在各参数上绝对差之和（单位与参数一致，跨参数直接相加）。")
    lines.append("- 真实响应：把推荐点代入案例声明的响应函数得到的值；与最优值之差 `response_gap` 以“变差幅度”计，非负表示劣于最优。")
    lines.append("- 预算内运行数：计划运行数在同时满足 `planned_runs*成本 <= 预算上限` 与 `planned_runs <= max_runs` 时计入，否则记 0。")
    lines.append("- 基线排期按参数域的完整网格点数计算，代表“不核算预算、直接扫全域”的朴素做法。")
    lines.append("")
    lines.append("## 逐例结果")
    lines.append("")
    for case in payload["cases"]:
        direction = "最大化" if case["gold"]["direction"] == "maximize" else "最小化"
        lines.append("### `%s`" % case["case_id"])
        lines.append("")
        lines.append("- 目标方向：%s；真实最优 %s，最优响应 %s。"
                     % (direction, json.dumps(case["gold"]["optimum"], ensure_ascii=False, sort_keys=True),
                        case["gold"]["true_response_at_optimum"]))
        lines.append("")
        lines.append("| 方法 | 推荐点 | L1 距离 | 真实响应 | 与最优之差 | 计划运行数 | 计划成本 | 预算内 | 预算内运行数 |")
        lines.append("|---|---|---|---|---|---|---|---|---|")
        for name, key in (("技能", "skill"), ("基线", "baseline")):
            entry = case[key]
            lines.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
                name,
                json.dumps(entry["recommended_values"], ensure_ascii=False, sort_keys=True),
                entry["l1_distance"], entry["true_response"], entry["response_gap"],
                entry["planned_runs"], entry["planned_cost"],
                "是" if entry["within_budget"] else "否", entry["runs_within_budget"],
            ))
        lines.append("")
        lines.append("- 技能 `status`：`%s`，模型 `%s`，推荐来源 `%s`。"
                     % (case["skill"]["status"], case["skill"]["model_status"], case["skill"]["source"]))
        lines.append("- 增益：L1 减少 %s，与最优的响应差缩小 %s，预算内运行数增加 %s。"
                     % (case["gain"]["l1_improvement"], case["gain"]["response_gap_improvement"],
                        case["gain"]["runs_within_budget_delta"]))
        lines.append("")

    summary = payload["summary"]
    lines.append("## 汇总")
    lines.append("")
    lines.append("| 指标 | 技能 | 基线 |")
    lines.append("|---|---|---|")
    lines.append("| L1 距离合计 | %s | %s |" % (summary["skill_l1_total"], summary["baseline_l1_total"]))
    lines.append("| 与最优的响应差合计 | %s | %s |" % (summary["skill_gap_total"], summary["baseline_gap_total"]))
    lines.append("| 预算内运行数合计 | %s | %s |" % (summary["skill_runs_within_budget"], summary["baseline_runs_within_budget"]))
    lines.append("| 全部案例严格更优 | %s | - |" % str(summary["skill_strictly_better_on_all_cases"]).lower())
    lines.append("")
    lines.append("## 复现")
    lines.append("")
    lines.append("```bash")
    lines.append("python bench/run_bench.py")
    lines.append("```")
    lines.append("")
    lines.append("脚本重写 `bench/bench_metrics.json` 与 `bench/bench_report.md`；同一输入重复运行字节一致。")
    lines.append("")
    return "\n".join(lines)


def main():
    names = sorted(name for name in os.listdir(CASE_DIR) if name.endswith(".json"))
    results = []
    for name in names:
        case_path = os.path.join(CASE_DIR, name)
        gold_path = os.path.join(GOLD_DIR, name)
        if not os.path.isfile(gold_path):
            raise RuntimeError("missing gold file for %s" % name)
        results.append(benchmark_case(case_path, gold_path))

    summary = {
        "cases": len(results),
        "skill_l1_total": round6(sum(r["skill"]["l1_distance"] for r in results)),
        "baseline_l1_total": round6(sum(r["baseline"]["l1_distance"] for r in results)),
        "skill_gap_total": round6(sum(r["skill"]["response_gap"] for r in results)),
        "baseline_gap_total": round6(sum(r["baseline"]["response_gap"] for r in results)),
        "skill_runs_within_budget": sum(r["skill"]["runs_within_budget"] for r in results),
        "baseline_runs_within_budget": sum(r["baseline"]["runs_within_budget"] for r in results),
        "skill_strictly_better_on_all_cases": all(r["gain"]["skill_strictly_better"] for r in results),
    }
    payload = {"protocol_version": PROTOCOL, "cases": results, "summary": summary}

    with open(os.path.join(BENCH_DIR, "bench_metrics.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")
    with open(os.path.join(BENCH_DIR, "bench_report.md"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(render_report(payload))

    sys.stdout.write("cases=%d skill_l1=%s baseline_l1=%s strict_win=%s\n" % (
        summary["cases"], summary["skill_l1_total"], summary["baseline_l1_total"],
        str(summary["skill_strictly_better_on_all_cases"]).lower(),
    ))
    return 0


if __name__ == "__main__":
    sys.exit(main())
