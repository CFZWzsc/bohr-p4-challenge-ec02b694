# Runtime contract

Bohrium Playground Period 4 submission — challenge `challenge-ec02b694` (track: `experimental-design`).

This repository holds the complete skill package for the challenge: the skill
definition, its executable pipeline and all supporting documents. No precomputed
answers, private data or credentials are included.

## Skill

- Name: `bounded-experiment-parameter-optimizer`
- Summary: Use when an experimental-design case provides finite parameter domains, equipment or safety bounds, response observations and a run budget, and asks for recommended parameter values, feasible intervals or a search strategy; run scripts/run_skill.py for a deterministic constraint-aware search with explicit cost and stop criteria.

## Contents

| File |
|------|
| `SKILL.md` |
| `examples/demo-case/case.json` |
| `examples/quickstart.md` |
| `scripts/run_skill.py` |
| `README.md` |

## How to run

```bash
python scripts/sk_entry.py --input /input --work /app/work --out /app/output
```

A single deterministic pass reads `/input`, computes the deliverable and writes a
contract-complete `/app/output/result.json` plus the human-readable review files
described in `SKILL.md`. The same input always produces byte-identical output; no
network access is used, and fields the materials cannot support are reported
explicitly instead of being left empty.
