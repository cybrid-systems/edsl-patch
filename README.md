# edsl-patch

**Post-training for Aura EDSL query + synthesis patches.** Not a Unify span. Not a Strand loop.

Given an Aura program, the trained model emits a structured patch sequence the host already knows how to apply — query first, then one hard synthesis. Not a free Lisp essay. Apply never calls an LLM.

```
Aura source
    →  patch sequence
         query*  (find | def-use | root)
         synthesis  (rebind | fill)
    →  apply on Aura  (set-code → query → mutate:rebind)
    →  keep iff post-source matches
```

## What this is

| In | Out |
|----|-----|
| Aura program + known transform | One **patch sequence** |
| Host: [Aura](https://github.com/cybrid-systems/aura) `(query :op)` / `mutate:rebind` | Ops the engine already has |

A patch is a JSON array (see `schema/patch.md`). Query locates. Synthesis mutates. A lambda body is allowed **only** as `rebind.body`, never as the whole answer.

## What this is not

- Not Aura (language/host).
- Not Strand (the seed that produces some traces).
- Not Unify (live MiniMax evolve + issue pump).
- Not live `synthesize:define` (nested LLM).
- Not v1 control-policy (`skip` / `persist` / `restore` / `yield`) — later track.
- Weights and raw dumps stay out of git (`checkpoints/`, `data/raw/`).

## Layout

```text
edsl-patch/
├── schema/patch.md     # legal query + synthesis ops
├── schema/sample.md    # SFT jsonl record
├── schema/apply.md     # host apply I/O
├── schema/collect.md   # git harvest from Unify KV / spans
├── lessons/            # teacher seeds (source_0 + source_1 intent)
├── catalog/            # L0 plants + L1 rewrites; catalog/projects/ budget
├── lib/farm.aura       # in-process star-mode plant/query/rebind
├── lib/teacher.aura    # namer / binder / helper agents (no mutate)
├── examples/           # apply-verified goldens
├── scripts/            # apply / ingest / teach / collect / farm / export_sft
└── tests/              # legal + apply + teacher + farm + budget
```

## Apply (host)

Sibling checkouts, same parent as Strand:

```text
../aura-grok/build/aura
```

```bash
python3 scripts/apply.py --sample examples/identity-to-abs.jsonl

python3 -m unittest discover -s tests -v

python3 scripts/ingest.py                  # cartesian catalog → data/raw/verified.jsonl
python3 scripts/teach.py                   # teacher lessons + multi-agent variants
python3 scripts/collect.py --doctor        # sibling + Aura layout (no jsonl)
python3 scripts/collect.py --limit 5       # real Unify KV / span git rebinds (cap before apply)
python3 scripts/farm.py --rounds 24        # star-mode control transforms → data/raw/farm.jsonl
python3 scripts/rollout.py --project twin-step --host dry-world --depth 4 --forks 4 --rounds 1
python3 scripts/rollout.py --host aura --project session-hot --depth 1 --forks 2 --rounds 1 --plant tick-hold
python3 scripts/rollout.py --project arith-core --plant arith-core.p0 --depth 1 --forks 4 --rounds 1
python3 scripts/rollout.py --project kv-mini --plant kv-mini.p0 --depth 1 --forks 4 --rounds 1
python3 scripts/farm.py --mode path --depth 4 --rounds 12   # chain post-source, re-plant every 4
python3 scripts/export_sft.py --profile dialect data/raw/verified.jsonl data/raw/teacher.jsonl
python3 scripts/export_sft.py --profile commercial \
  data/raw/farm-world-twin-step.jsonl data/raw/farm-world-session-hot.jsonl \
  data/raw/refuse.jsonl data/raw/farm.jsonl data/raw/teacher.jsonl
```

A `rebind` patch is:

```scheme
(query :find "f")
(mutate:rebind "f" "(lambda (x) (if (< x 0) (* x -1) x))" "abs")
```

Decide / persist / restore stay Strand meanings and are **not** v1 training targets. Poison must not become a positive synthesis label.

Farm samples are star-mode control transforms (`lib/farm.aura`). Git harvest stays `collect.py`. Teacher workers still do not mutate.

`--profile commercial` mix: twin-step 40%, session-hot 20%, refuse 20%, L0 dialect 15%, teacher/business 5%. Empty vertical buckets are an error (exit 2), not silent arith fill — pass `--allow-partial` only for fixture tests. Commercial also refuses to emit if twin world/path keeps < 50 or session keeps < 30 unless `--allow-partial`. Depth-v2 farms (#33–#36) are a prerequisite. Drops: quote-only session (no `tick`), hardcoded `energy: 12.4` / `t: 40` demo observe, missing observe on step/tick plants. `--profile dialect` is the old flat concat. Eval holdouts are never export inputs. Rollout JSONL: only `kind=hop` with `sft=true` and `advantage>0` (see `schema/rollout.md`).

## Grok Build

```bash
cd edsl-patch
grok
```

Then `/goal` the **open issue number** only, e.g. implement #2 exactly. Contract: `AGENTS.md`. Do not expand to other issues. Do not commit `data/raw/`. Default farm budget is `smoke` (`catalog/projects/BUDGET.md`).

## Session budget (Grok Build)

Default is `smoke`: 20 farm keeps, collect `--limit 5`, **zero** catalog edits.
Auto-plan never selects `full` (3000 × 8). Host farm does not spend Grok tokens.

```bash
python3 scripts/farm_budget.py --plan --all
```

See `catalog/projects/BUDGET.md`. Override with `EDSL_PATCH_BUDGET=small` or `catalog/projects/budget.env` (gitignored).

## License

Apache License 2.0
