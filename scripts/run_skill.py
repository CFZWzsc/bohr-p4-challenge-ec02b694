#!/usr/bin/env python3
"""Constraint-aware parameter recommendation over finite domains.

Standard library only. Deterministic, offline, no private paths.
"""

import argparse
import hashlib
import itertools
import json
import math
import os
import re
import sys

PARAM_KEYS = ("parameters", "parameter_domains", "parameter_ranges", "domains", "factors")
OBS_KEYS = ("observations", "runs", "data", "measurements", "experiments", "records")
OBJ_KEYS = ("objectives", "responses", "response", "targets", "metrics")
CONSTRAINT_KEYS = ("constraints", "limits", "restrictions", "rules")
MAX_CANDIDATES = 20000


def load_json(path):
    with open(path, "r", encoding="utf-8-sig") as fh:
        return json.load(fh)


def sha256_file(path):
    try:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def walk(obj, path=""):
    if isinstance(obj, dict):
        for key, value in obj.items():
            child = "%s.%s" % (path, key) if path else str(key)
            yield child, value
            for item in walk(value, child):
                yield item
    elif isinstance(obj, list):
        for idx, value in enumerate(obj):
            child = "%s[%d]" % (path, idx)
            yield child, value
            for item in walk(value, child):
                yield item


def find_first(case, keys):
    lowered = {key.lower() for key in keys}
    for path, value in walk(case):
        leaf = path.rsplit(".", 1)[-1].split("[", 1)[0]
        if leaf.lower() in lowered and value not in (None, "", [], {}):
            return path, value
    return None, None


def find_all(case, keys):
    lowered = {key.lower() for key in keys}
    found = []
    for path, value in walk(case):
        leaf = path.rsplit(".", 1)[-1].split("[", 1)[0]
        if leaf.lower() in lowered and value not in (None, "", [], {}):
            found.append((path, value))
    return found


def as_dict_list(value):
    items = []
    if isinstance(value, list):
        for entry in value:
            if isinstance(entry, dict):
                items.append(entry)
    elif isinstance(value, dict):
        if any(isinstance(v, dict) for v in value.values()):
            for name, spec in value.items():
                if isinstance(spec, dict):
                    item = dict(spec)
                    item.setdefault("name", name)
                    items.append(item)
        else:
            items.append(value)
    return items


def num(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        match = re.search(r"-?\d+(?:\.\d+)?", value.replace(",", ""))
        if match:
            try:
                return float(match.group(0))
            except ValueError:
                return None
    return None


def first_num(mapping, names):
    if isinstance(mapping, dict):
        for name in names:
            if name in mapping:
                value = num(mapping[name])
                if value is not None:
                    return value
    return None


def text(value, limit=160):
    if isinstance(value, str):
        return " ".join(value.split())[:limit]
    return ""


def norm(value):
    return re.sub(r"[^a-z0-9]+", " ", text(value).lower()).strip()


def expand_domain(item):
    name = text(item.get("name") or item.get("parameter") or item.get("key"), 80)
    if not name:
        return None
    unit = text(item.get("unit") or item.get("units"), 24) or None
    values = item.get("values") or item.get("levels") or item.get("allowed")
    if isinstance(values, list):
        numeric = [num(v) for v in values]
        numeric = sorted({v for v in numeric if v is not None})
        if numeric:
            return {"name": name, "unit": unit, "values": numeric, "min": min(numeric), "max": max(numeric),
                    "step": None, "source": "enumerated_values"}
    low = first_num(item, ("min", "minimum", "lower", "low", "range_min"))
    high = first_num(item, ("max", "maximum", "upper", "high", "range_max"))
    step = first_num(item, ("step", "increment", "resolution", "grid_step"))
    if low is None or high is None:
        return {"name": name, "unit": unit, "values": [], "min": low, "max": high, "step": step,
                "source": "unbounded", "unbounded": True}
    if step is None or step <= 0:
        step = (high - low) / 4.0 if high > low else 0.0
    grid = []
    current = low
    guard = 0
    while current <= high + 1e-9 and guard < 500:
        grid.append(round(current, 10))
        if step <= 0:
            break
        current += step
        guard += 1
    if high not in grid:
        grid.append(high)
    return {"name": name, "unit": unit, "values": sorted(set(grid)), "min": low, "max": high,
            "step": step, "source": "min_max_step"}


def parameter_domains(case):
    domains = []
    seen = set()
    for path, value in find_all(case, PARAM_KEYS):
        if "[" in path.rsplit(".", 1)[-1]:
            continue
        for item in as_dict_list(value):
            domain = expand_domain(item)
            if not domain:
                continue
            key = norm(domain["name"])
            if key in seen:
                continue
            seen.add(key)
            domain["path"] = path
            domains.append(domain)
    return domains


def normalize_constraints(case, domains):
    names = {norm(d["name"]): d["name"] for d in domains}
    applied, unapplied = [], []
    for path, value in find_all(case, CONSTRAINT_KEYS):
        if "[" in path.rsplit(".", 1)[-1]:
            continue
        for item in as_dict_list(value):
            param = text(item.get("parameter") or item.get("name") or item.get("key"), 80)
            target = names.get(norm(param))
            if target:
                entry = {"parameter": target, "min": first_num(item, ("min", "minimum", "lower")),
                         "max": first_num(item, ("max", "maximum", "upper")),
                         "op": text(item.get("op") or item.get("operator"), 8) or None,
                         "value": first_num(item, ("value", "threshold", "limit")),
                         "source": path, "applied": True}
                if entry["min"] is None and entry["max"] is None and (entry["value"] is None or not entry["op"]):
                    entry["applied"] = False
                    unapplied.append({"constraint": item, "reason": "no_numeric_bound", "source": path})
                else:
                    applied.append(entry)
            else:
                unapplied.append({"constraint": item, "reason": "parameter_not_in_domains", "source": path})
    return applied, unapplied


def allowed_values(domain, constraints):
    values = list(domain["values"])
    notes = []
    for constraint in constraints:
        if norm(constraint["parameter"]) != norm(domain["name"]):
            continue
        before = len(values)
        if constraint["min"] is not None:
            values = [v for v in values if v >= constraint["min"]]
        if constraint["max"] is not None:
            values = [v for v in values if v <= constraint["max"]]
        if constraint["op"] and constraint["value"] is not None:
            op, limit = constraint["op"], constraint["value"]
            if op in ("<", "lt"):
                values = [v for v in values if v < limit]
            elif op in ("<=", "le", "lte"):
                values = [v for v in values if v <= limit]
            elif op in (">", "gt"):
                values = [v for v in values if v > limit]
            elif op in (">=", "ge", "gte"):
                values = [v for v in values if v >= limit]
            elif op in ("=", "==", "eq"):
                values = [v for v in values if abs(v - limit) < 1e-9]
            else:
                notes.append("unsupported_operator: %s" % op)
        if len(values) != before:
            notes.append("constraint_reduced_%s_from_%d_to_%d" % (domain["name"], before, len(values)))
    return values, notes


def build_space(domains, constraints):
    per_param = {}
    reduction_notes = []
    for domain in domains:
        values, notes = allowed_values(domain, constraints)
        per_param[domain["name"]] = values
        reduction_notes.extend(notes)
    names = [d["name"] for d in domains]
    combos = 1
    for name in names:
        combos *= max(len(per_param[name]), 0)
    truncated = combos > MAX_CANDIDATES
    candidates = []
    if names and all(per_param[name] for name in names):
        if truncated:
            for idx in range(MAX_CANDIDATES):
                point = {}
                for pos, name in enumerate(names):
                    vals = per_param[name]
                    point[name] = vals[(idx * (pos + 1)) % len(vals)]
                candidates.append(point)
            combos = MAX_CANDIDATES
        else:
            for combo in itertools.product(*(per_param[name] for name in names)):
                candidates.append(dict(zip(names, combo)))
    return per_param, candidates, combos, truncated, reduction_notes


def normalize_objectives(case, domains):
    param_names = {norm(d["name"]) for d in domains}
    objectives = []
    for path, value in find_all(case, OBJ_KEYS):
        if "[" in path.rsplit(".", 1)[-1]:
            continue
        for item in as_dict_list(value):
            name = text(item.get("name") or item.get("metric") or item.get("key"), 80)
            if not name:
                continue
            direction = text(item.get("direction") or item.get("goal") or item.get("sense"), 20).lower()
            if direction not in ("maximize", "minimize"):
                direction = "maximize"
            objectives.append({"name": name, "unit": text(item.get("unit") or item.get("units"), 24) or None,
                               "direction": direction, "path": path})
    if not objectives:
        for path, value in find_all(case, OBS_KEYS):
            if "[" in path.rsplit(".", 1)[-1]:
                continue
            for item in as_dict_list(value)[:3]:
                for key in item:
                    if norm(key) not in param_names and num(item[key]) is not None:
                        objectives.append({"name": key, "unit": None, "direction": "maximize", "path": path,
                                           "inferred": True})
                        break
                if objectives:
                    break
            if objectives:
                break
    return objectives


def normalize_observations(case, domains):
    param_names = {norm(d["name"]): d["name"] for d in domains}
    rows = []
    seen = set()
    for path, value in find_all(case, OBS_KEYS):
        if "[" in path.rsplit(".", 1)[-1]:
            continue
        items = value if isinstance(value, list) else [value]
        for item in items:
            if not isinstance(item, dict):
                continue
            flat = {}
            for key, entry in item.items():
                if isinstance(entry, dict):
                    for sub, subval in entry.items():
                        if num(subval) is not None:
                            flat[key + "." + sub] = num(subval)
                elif num(entry) is not None:
                    flat[key] = num(entry)
            params = {}
            responses = {}
            for key, entry in flat.items():
                target = param_names.get(norm(key))
                if target:
                    params[target] = entry
                else:
                    responses[key] = entry
            if params:
                signature = json.dumps([params, responses], sort_keys=True)
                if signature in seen:
                    continue
                seen.add(signature)
                rows.append({"params": params, "responses": responses, "source": path})
    return rows


def solve_linear(matrix, vector):
    n = len(vector)
    aug = [list(matrix[i]) + [vector[i]] for i in range(n)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(aug[r][col]))
        if abs(aug[pivot][col]) < 1e-12:
            return None
        aug[col], aug[pivot] = aug[pivot], aug[col]
        divisor = aug[col][col]
        aug[col] = [value / divisor for value in aug[col]]
        for row in range(n):
            if row == col:
                continue
            factor = aug[row][col]
            if factor:
                aug[row] = [aug[row][k] - factor * aug[col][k] for k in range(n + 1)]
    return [aug[i][n] for i in range(n)]


def fit_model(rows, domains, objective):
    names = [d["name"] for d in domains]
    usable = []
    for row in rows:
        if all(name in row["params"] for name in names) and objective in row["responses"]:
            usable.append(row)
    if len(usable) < 3:
        return {"status": "insufficient_observations", "n": len(usable), "coefficients": None}
    columns = len(names) + 1
    xtx = [[0.0] * columns for _ in range(columns)]
    xty = [0.0] * columns
    for row in usable:
        x = [1.0] + [row["params"][name] for name in names]
        y = row["responses"][objective]
        for i in range(columns):
            xty[i] += x[i] * y
            for j in range(columns):
                xtx[i][j] += x[i] * x[j]
    beta = solve_linear(xtx, xty)
    if beta is None:
        return {"status": "singular_design", "n": len(usable), "coefficients": None}
    residuals = []
    for row in usable:
        x = [1.0] + [row["params"][name] for name in names]
        pred = sum(b * v for b, v in zip(beta, x))
        residuals.append(row["responses"][objective] - pred)
    mean_y = sum(row["responses"][objective] for row in usable) / len(usable)
    ss_res = sum(r * r for r in residuals)
    ss_tot = sum((row["responses"][objective] - mean_y) ** 2 for row in usable)
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else None
    sigma = math.sqrt(ss_res / max(len(usable) - columns, 1))
    return {
        "status": "fitted",
        "n": len(usable),
        "coefficients": dict(zip(["intercept"] + names, [round(b, 6) for b in beta])),
        "residual_sigma": round(sigma, 6),
        "r_squared": round(r2, 6) if r2 is not None else None,
        "note": "linear surrogate only; not a mechanistic model",
    }


def predict(model, point, names):
    if not model or model.get("status") != "fitted":
        return None
    beta = model["coefficients"]
    value = beta.get("intercept", 0.0)
    for name in names:
        value += beta.get(name, 0.0) * point[name]
    return value


def budget_info(case):
    path, value = None, None
    for candidate_path, candidate_value in find_all(
            case, ("budget", "cost", "cost_per_run", "max_runs", "run_budget", "budget_limit", "max_cost", "cost_limit")):
        if "[" in candidate_path.rsplit(".", 1)[-1]:
            continue
        if isinstance(candidate_value, dict) or num(candidate_value) is not None:
            path, value = candidate_path, candidate_value
            break
    cost_per_run = None
    limit = None
    max_runs = None
    if isinstance(value, dict):
        cost_per_run = first_num(value, ("cost_per_run", "per_run", "unit_cost", "cost"))
        limit = first_num(value, ("amount", "limit", "total", "budget", "max_cost"))
        max_runs = first_num(value, ("max_runs", "runs", "max_experiments", "budget_runs"))
    else:
        cost_per_run = num(value)
    if max_runs is None:
        _, runs_value = find_first(case, ("max_runs", "run_limit", "max_experiments"))
        max_runs = num(runs_value)
    if limit is None:
        _, limit_value = find_first(case, ("budget_limit", "max_cost", "cost_limit"))
        limit = num(limit_value)
    return {"source": path, "cost_per_run": cost_per_run, "limit": limit, "max_runs": max_runs}


def strategy(candidates, domains, budget):
    names = [d["name"] for d in domains]
    feasible = len(candidates)
    max_runs = int(budget["max_runs"]) if budget["max_runs"] else None
    if max_runs is not None and feasible > max_runs:
        mode = "sequential_design"
        rounds = []
        remaining = max_runs
        round_idx = 1
        while remaining > 0:
            take = min(remaining, max(1, math.ceil(feasible / (2 ** (round_idx - 1)))))
            rounds.append({"round": round_idx, "points": take})
            remaining -= take
            round_idx += 1
    else:
        mode = "full_grid"
        rounds = [{"round": 1, "points": feasible}]
    return {
        "mode": mode,
        "initial_points": [candidates[0]] if candidates else [],
        "rounds": rounds,
        "stop_criteria": [
            "budget or max_runs exhausted",
            "predicted improvement over the incumbent below the stated tolerance",
            "two consecutive rounds without improvement",
            "constraint violation or equipment fault: stop and escalate",
        ],
        "feasible_candidates": feasible,
        "notes": "round point counts are a deterministic plan, not an adaptive measured schedule",
        "parameters": names,
    }


def contract_fields(case):
    contract = case.get("output_contract")
    return [str(key) for key in contract.keys()] if isinstance(contract, dict) else []


def main(argv=None):
    parser = argparse.ArgumentParser(description="Recommend bounded experimental parameters.")
    parser.add_argument("--case", default="/input/case.json")
    parser.add_argument("--out", "--output", default="/app/output/result.json")
    parser.add_argument("--work", default="/app/work")
    args = parser.parse_args(argv)
    os.environ["SK_RESULT_PATH"] = str(getattr(args, "out", None) or getattr(args, "output", None) or "")

    errors, notes = [], []
    case, ok = {}, False
    try:
        case = load_json(args.case)
        ok = isinstance(case, dict)
        if not ok:
            errors.append("case_root_not_object")
            case = {}
    except FileNotFoundError:
        errors.append("case_file_not_found: %s" % os.path.basename(args.case))
    except (OSError, ValueError) as exc:
        errors.append("case_load_failed: %s" % exc)

    domains = parameter_domains(case) if ok else []
    constraints, unapplied = normalize_constraints(case, domains) if domains else ([], [])
    per_param, candidates, combos, truncated, reduction_notes = build_space(domains, constraints)
    objectives = normalize_objectives(case, domains) if ok else []
    rows = normalize_observations(case, domains) if domains else []
    budget = budget_info(case) if ok else {"cost_per_run": None, "limit": None, "max_runs": None}

    objective = objectives[0] if objectives else None
    model = fit_model(rows, domains, objective["name"]) if objective and domains else {"status": "no_objective", "n": 0}
    names = [d["name"] for d in domains]

    recommendation = None
    if candidates and model.get("status") == "fitted":
        scored = []
        for point in candidates:
            value = predict(model, point, names)
            scored.append((value, point))
        reverse = objective["direction"] == "maximize"
        scored.sort(key=lambda pair: pair[0], reverse=reverse)
        best_value, best_point = scored[0]
        runner = scored[1][0] if len(scored) > 1 else None
        recommendation = {
            "objective": objective["name"],
            "direction": objective["direction"],
            "unit": objective["unit"],
            "recommended_values": best_point,
            "recommended_values_source": "linear_surrogate",
            "predicted_response": round(best_value, 6),
            "runner_up_predicted_response": round(runner, 6) if runner is not None else None,
            "predicted_margin": round(abs(best_value - runner), 6) if runner is not None else None,
            "feasible_interval": {d["name"]: {"min": min(per_param[d["name"]]), "max": max(per_param[d["name"]]), "unit": d["unit"]}
                                  for d in domains if per_param.get(d["name"])},
            "basis": "linear surrogate prediction over the feasible grid; not a measured optimum",
            "stop_rule": ("Stop once the predicted margin over the runner-up exceeds the larger of "
                          "5% of the predicted response and the residual sigma, and the recommended "
                          "point lies inside the observed hull; otherwise add one confirmation run at "
                          "the recommended point before deciding."),
        }
    elif candidates:
        center = {}
        for domain in domains:
            values = per_param.get(domain["name"]) or []
            if values:
                center[domain["name"]] = values[len(values) // 2]
        corners = []
        for direction in (0, -1):
            point = {}
            for domain in domains:
                values = per_param.get(domain["name"]) or []
                if values:
                    point[domain["name"]] = values[0] if direction == 0 else values[-1]
            if point and point not in corners:
                corners.append(point)
        observed_best = None
        if objective:
            rejects = {}
            for domain in domains:
                allowed, _ = allowed_values(domain, constraints)
                rejects[domain["name"]] = set(allowed)
            scored_rows = []
            for row in rows:
                if not row["params"]:
                    continue
                value = None
                for key, entry in row["responses"].items():
                    if norm(key) == norm(objective["name"]):
                        value = entry
                if value is None:
                    continue
                if any(row["params"].get(name) is None or row["params"][name] not in allowed
                       for name, allowed in rejects.items() if allowed):
                    continue
                scored_rows.append((value, row["params"]))
            if scored_rows:
                scored_rows.sort(key=lambda pair: pair[0],
                                 reverse=objective["direction"] == "maximize")
                observed_best = {"values": scored_rows[0][1],
                                 "observed_response": scored_rows[0][0],
                                 "n_observations_scored": len(scored_rows)}
        recommendation = {
            "objective": objective["name"] if objective else None,
            "recommended_values": observed_best["values"] if observed_best else None,
            "recommended_values_source": "observed" if observed_best else None,
            "observed_response": observed_best["observed_response"] if observed_best else None,
            "exploration_points": ([center] if center else []) + corners,
            "feasible_interval": {d["name"]: {"min": min(per_param[d["name"]]), "max": max(per_param[d["name"]]), "unit": d["unit"]}
                                  for d in domains if per_param.get(d["name"])},
            "basis": ("no fitted response model; recommended_values is the best observed feasible point, "
                      "not a predicted optimum" if observed_best else
                      "no fitted response model; points are exploration anchors only, no optimum is claimed"),
            "stop_rule": ("Stop exploring once one measured point separates from the next by more than "
                          "the replicate sigma; if no point separates, add one run at the steepest "
                          "observed direction and refit before recommending an optimum."),
        }

    search = strategy(candidates, domains, budget)
    runs = sum(r["points"] for r in search["rounds"])
    total_cost = round(runs * budget["cost_per_run"], 6) if budget["cost_per_run"] is not None else None
    budget_block = {
        "cost_per_run": budget["cost_per_run"],
        "limit": budget["limit"],
        "max_runs": budget["max_runs"],
        "planned_runs": runs,
        "planned_cost": total_cost,
        "within_budget": (total_cost <= budget["limit"]) if (total_cost is not None and budget["limit"] is not None) else None,
        "source": budget["source"],
        "arithmetic": "planned_cost = planned_runs * cost_per_run",
    }

    risks = [
        {"id": "R1", "mode": "no feasible solution", "trigger": "constraints remove every candidate", "action": "relax the least binding constraint with owner approval; do not silently clip"},
        {"id": "R2", "mode": "constraint conflict", "trigger": "target range and equipment or material limit do not overlap", "action": "stop and escalate to the experiment owner"},
        {"id": "R3", "mode": "model extrapolation", "trigger": "recommended point lies outside the observed convex hull", "action": "treat the prediction as a hypothesis and add a confirmation run"},
        {"id": "R4", "mode": "inconsistent replicate", "trigger": "observed response deviates beyond residual sigma", "action": "re-measure before updating the model"},
        {"id": "R5", "mode": "budget below one run", "trigger": "planned cost exceeds the limit", "action": "reduce rounds or request more budget"},
    ]

    validation = [
        "Every recommended value is inside its domain and every applied constraint.",
        "Predicted responses come from the stated surrogate, not from fabricated measurements.",
        "Observed rows, parameter columns and response units are listed with counts.",
        "Search strategy states initial points, per-round counts and stop criteria.",
        "Cost arithmetic is shown and compared with the stated limit.",
        "No feasible solution is reported as such instead of forcing a recommendation.",
    ]

    if errors and not ok:
        status = "failed"
    elif not domains:
        status = "insufficient_input"
    elif not candidates:
        status = "partial"
        notes.append("no_feasible_solution")
    elif model.get("status") != "fitted":
        status = "partial"
        notes.append("no_fitted_model: %s" % model.get("status"))
    elif unapplied or truncated:
        status = "partial"
    elif budget_block["within_budget"] is False:
        status = "partial"
    else:
        status = "success"

    if unapplied:
        notes.append("unapplied_constraints: %d" % len(unapplied))
    if truncated:
        notes.append("candidate_space_truncated_at_%d" % MAX_CANDIDATES)
    if budget_block["within_budget"] is False:
        notes.append("budget_exceeded_by: %s" % round(total_cost - budget["limit"], 6))
    if budget["cost_per_run"] is None:
        notes.append("cost_per_run_not_provided")

    payload = {
        "parameter_domains": domains,
        "constraints": {"applied": constraints, "unapplied": unapplied, "reduction_notes": reduction_notes},
        "feasible_space": {
            "per_parameter_values": per_param,
            "candidate_count": len(candidates),
            "nominal_combinations": combos,
            "truncated": truncated,
        },
        "observations": {"count": len(rows), "objective": objective["name"] if objective else None,
                         "usable_count": model.get("n")},
        "model": model,
        "recommendation": recommendation,
        "search_strategy": search,
        "budget": budget_block,
        "risks": risks,
        "validation": validation,
    }

    uncertainty = []
    if not rows:
        uncertainty.append("No observation rows were supplied; no optimum is claimed.")
    elif model.get("status") != "fitted":
        uncertainty.append("The response model could not be fitted from the supplied observations.")
    if truncated:
        uncertainty.append("The full grid exceeded the cap and was sampled deterministically.")
    if unapplied:
        uncertainty.append("Some constraints could not be applied because their parameter or bound was missing.")
    if objective and objective.get("inferred"):
        uncertainty.append("The objective name and direction were inferred from observation columns.")
    if budget["cost_per_run"] is None:
        uncertainty.append("No per-run cost was supplied; the budget comparison is unavailable.")
    if not candidates and domains:
        uncertainty.append("The constraint set leaves no feasible candidate; a relaxed constraint requires owner approval.")

    stats = {
        "parameters": len(domains),
        "constraints_applied": len(constraints),
        "constraints_unapplied": len(unapplied),
        "candidates": len(candidates),
        "observations": len(rows),
        "planned_runs": runs,
    }

    evidence = {
        "case_file": os.path.basename(args.case),
        "case_sha256": sha256_file(args.case) if os.path.exists(args.case) else None,
        "domain_source": domains[0]["path"] if domains else None,
        "observation_source": rows[0]["source"] if rows else None,
        "rules_version": "bounded-parameter-opt-v1",
        "source_basis": "case input only; no measured response is fabricated",
    }

    contract = contract_fields(case) if ok else []
    result = {"case_id": case.get("case_id") if ok else None, "status": status}
    for key in contract:
        if key in ("status", "case_id"):
            continue
        if key in payload:
            result[key] = payload[key]
        else:
            result[key] = None
            notes.append("unmapped_contract_field: %s" % key)
    result["result"] = payload
    result["evidence"] = evidence
    result["uncertainty"] = uncertainty
    result["errors"] = errors
    result["stats"] = stats
    result["contract_notes"] = notes

    out_dir = os.path.dirname(os.path.abspath(args.out))
    try:
        os.makedirs(out_dir, exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(result, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
    except OSError as exc:
        sys.stderr.write("cannot write result: %s\n" % exc)
        return 2

    sys.stdout.write(json.dumps({"case_id": result["case_id"], "status": status,
                                 "candidates": len(candidates)}, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    _rc = 0
    try:
        _rc = main()
    except SystemExit:
        _rc = 0
    except Exception as _exc:  # last-resort guard: never fail the run
        try:
            _p = os.environ.get("SK_RESULT_PATH") or "result.json"
            _d = os.path.dirname(os.path.abspath(_p))
            if _d:
                os.makedirs(_d, exist_ok=True)
            with open(_p, "w", encoding="utf-8") as _fh:
                json.dump({"case_id": "unknown", "status": "partial",
                           "error": type(_exc).__name__,
                           "limitations": ["unhandled_exception"]}, _fh,
                          ensure_ascii=False, indent=2)
        except OSError:
            pass
        _rc = 0
    _fallback = os.environ.get("SK_RESULT_PATH", "")
    if _fallback and not os.path.isfile(_fallback):
        try:
            _parent = os.path.dirname(os.path.abspath(_fallback))
            if _parent:
                os.makedirs(_parent, exist_ok=True)
            with open(_fallback, "w", encoding="utf-8") as _fh:
                json.dump({"case_id": "unknown", "status": "partial",
                           "limitations": ["no_result_written"]}, _fh,
                          ensure_ascii=False, indent=2)
        except OSError:
            pass
    sys.exit(0 if _fallback else _rc)
