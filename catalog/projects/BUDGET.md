# Session budget + usage estimates

Host farm (`farm_project.py` × Aura apply) does **not** call an LLM.
Grok Build tokens burn when an agent implements issues or extends
`catalog/projects/<id>/` after `catalog-exhausted`.

```
/goal Farm project arith-core under budget=small.
Use scripts/farm_loop.py --project arith-core --budget small.
Honor EDSL_PATCH_BUDGET if set; default smoke. Do not pass --budget full unless the operator said full.
Stop on quota, budget, wall, or max-loop. Do not commit data/raw.
```

```bash
python3 scripts/farm_budget.py --plan --all
python3 scripts/farm_budget.py --project arith-core --json
python3 scripts/collect.py --limit "$(python3 -c 'from farm_budget import resolve; print(resolve()["collect_limit"])')"
```

## Defaults (committed)

| knob | smoke (default) | small | medium | full (opt-in) |
|------|-----------------|-------|--------|----------------|
| farm keep / project | 20 | 80 | 400 | 3000 |
| max-loop | 1 | 2 | 4 | 8 |
| wall-seconds | 180 | 600 | 1800 | 7200 |
| catalog edits | 0 | 5 | 12 | 40 |
| collect `--limit` | 5 | 25 | 80 | 200 |

Auto (`--plan`) never selects `full`. Unset env → `smoke`.
A `/goal` that says 3000 without `--budget full` / `EDSL_PATCH_BUDGET=full` is clamped.

## How much data

Estimates use 520 B / farm row and 800 B / collect row (see `examples/identity-to-abs.jsonl` ≈ 369 B plus verify).

| track | what | default this session | if you later opt in `full` × 8 projects |
|-------|------|----------------------|-----------------------------------------|
| farm keep | apply-verified `query*+rebind` | 20 rows ≈ 10 KiB | 24 000 rows ≈ 12 MiB |
| collect git | real sibling rebinds | 5 candidates | cap 200 / session, grows with Unify git |
| teacher | lesson fanout | all 8 seeds, no extra Grok loop | still tiny |
| ingest cartesian | catalog pairs | = plants × rewrites | same, host-only |

Yield assumption: ~45% of attempts survive quality filters. Aura apply ≈ 120 ms / attempt → smoke host farm is seconds, medium is minutes, full per project is tens of minutes **on the host**, not on Grok.

## Estimated Grok usage

Bands are ±3×. Weekly warn line is 1.5M tokens.

| session shape | Grok tokens | when |
|---------------|-------------|------|
| host-only (`max-catalog-edits=0`, runner exists) | **0** | `--plan` reason `host-pairs-*` |
| implement missing runner/catalog | ~0.4M (0.13–1.2M) | first #11/#12 session |
| each catalog edit Grok writes | ~80k | only if pairs < remaining |
| each farm_loop re-entry overhead | ~40k | thinking + tool calls, no new code |

Do **not** generate rebind bodies with an LLM. That would be millions of tokens for 3k rows and is out of scope.

## Auto pick

```
missing runner or catalog     → smoke (implement, do not farm 3k)
keep >= target                → off
unused pairs cover remaining  → smoke|small|medium, catalog edits = 0
need growth, remaining ≤ 80   → small
otherwise                     → medium
never                         → full
```

Prints `FARM_PLAN project=… budget=… grok_tokens_est=… reason=…`

## Config surface

Numeric overrides after preset clamp: CLI > process env > `catalog/projects/budget.env` > preset table.
Committed `budget.default.env` only pins `EDSL_PATCH_BUDGET=smoke`.

```
EDSL_PATCH_BUDGET=small
FARM_TARGET=80
FARM_MAX_LOOP=2
FARM_WALL_SECONDS=600
FARM_MAX_CATALOG_EDITS=5
COLLECT_LIMIT=25
```
