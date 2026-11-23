# Runtime contract

Bohrium Playground Period 4 submission — challenge `challenge-ec02b694` (track: `experimental-design`).

This repository holds the complete skill package for the challenge: the skill
definition, its executable entry point and all supporting scripts. No precomputed
answers, private data or credentials are included.

## Skill

- Name: `bounded-experiment-parameter-optimizer`
- Summary: Use when an experimental-design case provides finite parameter domains, equipment or safety bounds, response observations and a run budget, and asks for recommended parameter values, feasible intervals or a search strategy; run scripts/run_skill.py for a deterministic constraint-aware search with explicit cost and stop criteria.

## Contents

| File |
|------|
| `SKILL.md` |
| `scripts/run_skill.py` |
| `README.md` |

## How to run

```bash
python scripts/run_skill.py --case /input/case.json --output /app/output/result.json
```

The entry point is `SKILL.md`; input/output contracts, error handling and a minimal
usage example are documented there.

## Notes

- Pure Python standard library; no network access required.
- The result JSON keeps the input case id, the main results, per-item evidence,
  a run status and an uncertainty section.
