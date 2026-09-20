# farm-project workflow

First action: resolve the session budget. Refuse to start when budget is `off` or target `0`.

```bash
python3 scripts/farm_budget.py --plan --project "$PROJECT"
python3 scripts/farm_loop.py --project "$PROJECT" --budget "${EDSL_PATCH_BUDGET:-smoke}"
```

If the plan line has `budget=off` or `target=0`, stop. Do not farm.

## Rules

- One project per Grok Build session.
- Do **not** call `/loop`.
- Do not escalate the preset mid-session.
- Do not pass `--budget full` unless the operator said full.
- Default is `smoke`.
- Do not commit `data/raw/`.
- On `catalog-exhausted`, edit only `catalog/projects/<id>/` up to `max-catalog-edits`, then `catalog.py --check --projects`.
