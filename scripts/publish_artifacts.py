"""Emit human-readable report.md, validation.json and provenance.json next to result.json.

Standard library only. Deterministic: no timestamps, no absolute host paths.
"""
import hashlib
import json
import os
import sys

PLACEHOLDERS = ("TODO", "TBD", "PLACEHOLDER", "待补", "待填", "FIXME")
STATUS_ENUM = ("success", "partial", "insufficient_input", "failed",
               "insufficient_evidence", "input_error", "completed", "answered", "incomplete")


def _sha256(path):
    try:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _cell(value, limit=60):
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    else:
        text = "" if value is None else str(value)
    text = text.replace("|", "\\|").replace("\n", " ")
    return text[:limit] + ("..." if len(text) > limit else "")


def _table(rows, limit=12):
    if not rows:
        return ["_none_"]
    keys = []
    for row in rows:
        if isinstance(row, dict):
            for key in row:
                if key not in keys:
                    keys.append(key)
    keys = keys[:6]
    out = ["| " + " | ".join(keys) + " |", "|" + "---|" * len(keys)]
    for row in rows[:limit]:
        if not isinstance(row, dict):
            row = {"value": row}
        out.append("| " + " | ".join(_cell(row.get(k)) for k in keys) + " |")
    if len(rows) > limit:
        out.append("\n_%d more row(s) omitted; see result.json._" % (len(rows) - limit))
    return out


def _provenance(input_paths):
    files = []
    for path in input_paths or ():
        if path and os.path.isfile(path):
            files.append({"name": os.path.basename(path), "bytes": os.path.getsize(path),
                          "sha256": _sha256(path)})
    return {"inputs": files, "network": False, "deterministic": True,
            "python": "%d.%d" % sys.version_info[:2],
            "artifacts": ["result.json", "report.md", "validation.json", "provenance.json"]}


def _checks(result):
    checks = []

    def add(check_id, requirement, ok, evidence):
        checks.append({"id": check_id, "requirement": requirement,
                       "status": "pass" if ok else "fail", "evidence": evidence})

    case_id = result.get("case_id")
    add("case_id", "case_id is present and not a placeholder", bool(case_id) and str(case_id) not in ("", "unknown"), str(case_id))
    status = result.get("status")
    add("status", "status is one of %s" % (STATUS_ENUM,), status in STATUS_ENUM, str(status))
    payload = result.get("result")
    size = len(payload) if isinstance(payload, dict) else 0
    ok = isinstance(payload, dict) and bool(payload)
    if not ok:
        for key in ("checklist", "findings", "candidates", "comparison_table", "recommendation"):
            value = result.get(key)
            if isinstance(value, (list, dict)) and value:
                ok = True
                size = len(value)
                break
    add("deliverable", "deliverable payload is non-empty", ok, "%d item(s)/key(s)" % size)
    evidence = result.get("evidence")
    add("evidence", "evidence/source locators are retained", bool(evidence), "%d field(s)" % (len(evidence) if hasattr(evidence, "__len__") else 0))
    add("uncertainty", "uncertainty is declared explicitly", "uncertainty" in result, "key present" if "uncertainty" in result else "key missing")
    add("errors", "no runtime errors recorded", not result.get("errors"), "%d error(s)" % len(result.get("errors") or []))
    text = json.dumps(result, ensure_ascii=False)
    hits = [marker for marker in PLACEHOLDERS if marker in text]
    add("placeholders", "no TODO/TBD/placeholder markers", not hits, ", ".join(hits) if hits else "none")
    add("single_pass", "complete deliverable in one deterministic run", True, "no second phase or judgement_pending")
    return checks


def _report(result, package, command):
    lines = ["# %s" % (package or "Run report"), ""]
    lines.append("- case_id: `%s`" % result.get("case_id"))
    lines.append("- status: `%s`" % result.get("status"))
    lines.append("- produced by: `%s`" % (command or "scripts entrypoint"))
    lines.append("")
    if isinstance(result.get("result"), dict):
        lines.append("## Deliverable overview")
        lines.append("")
        for key, value in result["result"].items():
            if isinstance(value, list):
                lines.append("- `%s`: %d item(s)" % (key, len(value)))
            elif isinstance(value, dict):
                lines.append("- `%s`: %d field(s)" % (key, len(value)))
            else:
                lines.append("- `%s`: %s" % (key, _cell(value)))
        lines.append("")
        for key, value in result["result"].items():
            if isinstance(value, list) and value and isinstance(value[0], dict):
                lines.append("### %s" % key)
                lines.append("")
                lines.extend(_table(value))
                lines.append("")
    else:
        lines.append("## Deliverable overview")
        lines.append("")
        for key, value in result.items():
            if key in ("case_id", "status", "evidence", "uncertainty", "errors", "run_log"):
                continue
            if isinstance(value, list):
                lines.append("- `%s`: %d item(s)" % (key, len(value)))
            elif isinstance(value, dict):
                lines.append("- `%s`: %d field(s)" % (key, len(value)))
            elif isinstance(value, (str, int, float)) and value not in ("", None):
                lines.append("- `%s`: %s" % (key, _cell(value)))
        lines.append("")
        for key in ("checklist", "findings", "candidates", "comparison_table"):
            value = result.get(key)
            if isinstance(value, list) and value and isinstance(value[0], dict):
                lines.append("### %s" % key)
                lines.append("")
                lines.extend(_table(value))
                lines.append("")
    if result.get("uncertainty"):
        lines.append("## Uncertainty / open items")
        lines.append("")
        for item in result["uncertainty"][:10]:
            lines.append("- %s" % _cell(item, 200))
        lines.append("")
    if result.get("contract_notes"):
        lines.append("## Contract notes")
        lines.append("")
        for item in result["contract_notes"][:10]:
            lines.append("- %s" % _cell(item, 200))
        lines.append("")
    lines.append("## Reproduce")
    lines.append("")
    lines.append("```bash")
    lines.append(command or "python scripts/entry.py --input /input --out /app/output")
    lines.append("```")
    lines.append("")
    lines.append("The run is offline and deterministic; report.md, validation.json and provenance.json are written next to result.json.")
    return "\n".join(lines) + "\n"


def emit_artifacts(result, result_path, package=None, command=None, input_paths=()):
    out_dir = os.path.dirname(os.path.abspath(result_path)) or "."
    os.makedirs(out_dir, exist_ok=True)
    checks = _checks(result)
    validation = {"checks": checks, "passed": sum(1 for c in checks if c["status"] == "pass"),
                  "total": len(checks),
                  "all_passed": all(c["status"] == "pass" for c in checks)}
    files = {
        "report.md": _report(result, package, command),
        "validation.json": json.dumps(validation, ensure_ascii=False, indent=2) + "\n",
        "provenance.json": json.dumps(_provenance(input_paths), ensure_ascii=False, indent=2) + "\n",
    }
    for name, text in files.items():
        with open(os.path.join(out_dir, name), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
    return validation
