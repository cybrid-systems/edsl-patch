# AGENTS.md — edsl-patch

Grok Build contract. One issue per session. Do not expand scope.

## What this is / is not

| Is | Is not |
|----|--------|
| Post-training data for Aura **query + synthesis** patches | Aura language/host |
| Host apply: `set-code` → `query` → `mutate:rebind` | Strand loop / Unify evolve |
| Offline hard `rebind` / `fill` | Live `synthesize:define` (nested LLM) |

See `README.md`. Weights and dumps stay out of git (`checkpoints/`, `data/raw/`).

## Legal patch (`schema/patch.md`)

One model output = one JSON **array**.

- ≥1 `kind: query`, then **exactly one** `kind: synthesis`
- Query ops: `find` \| `def-use` \| `root` (name-based only; never raw node ids)
- Synthesis v1 = `rebind` (`name`, `body`, `summary`); `fill` only with a registered template
- `rebind.body` is one `(lambda …)` form; two-arm `if` when `if` is used; no extra top-level `define`

## Illegal (refuse, do not emit)

- `eval`, extra `define` in body, shell, `fiber:spawn`
- `synthesize:define` / `synthesize:pipeline`
- Control-policy positives: `skip`, `persist`, `restore`, `yield`, `heal`
- Node-id query fields
- Synthesis before query, or more than one synthesis
- `set-code` / `mutate:rebind` / `eval-current` inside `lib/teacher.aura` workers

## Host

- Binary: `$AURA_BIN` or `../aura-grok/build/aura`
- Stdlib: `$AURA_LIB` or `../aura-grok/lib`
- `AURA_SANDBOX=off` `AURA_PIPELINE_STRICT=0`

## Tracks (jsonl, gitignored under `data/raw/`)

| Track | Script | Out |
|-------|--------|-----|
| ingest | `scripts/ingest.py` | `verified.jsonl` |
| teach | `scripts/teach.py` | `teacher.jsonl` |
| collect | `scripts/collect.py` | `business.jsonl` |
| farm | `scripts/farm.py` | `farm.jsonl` |

## Session budget

Default preset is **`smoke`**, never `full`. Honor `EDSL_PATCH_BUDGET` / `--budget` (`catalog/projects/BUDGET.md`). One issue, one project, one session. Do not call `/loop`. Do not escalate the preset mid-session. Stop reasons include `budget` and `wall` next to `quota` / `max-loop`. Parser lives in `scripts/farm_budget.py` (#19); do not reimplement it here.

## One-issue rule

Implement **only** the open issue in the `/goal`. Do not start sibling issues. Do not invent new patch kinds. Do not commit `data/raw/` or checkpoints.
