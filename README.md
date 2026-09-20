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
├── lib/teacher.aura    # namer / binder / helper agents (no mutate)
├── examples/           # apply-verified goldens
├── catalog/projects/   # typed plants + session budget
├── scripts/            # apply / ingest / teach / collect / export_sft / farm_budget
└── tests/              # legal + apply + teacher fanout + budget
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
python3 scripts/collect.py                 # real Unify KV / span git rebinds (incremental)
python3 scripts/export_sft.py data/raw/business.jsonl data/raw/teacher.jsonl data/raw/verified.jsonl
```

A `rebind` patch is:

```scheme
(query :find "f")
(mutate:rebind "f" "(lambda (x) (if (< x 0) (* x -1) x))" "abs")
```

Decide / persist / restore stay Strand meanings and are **not** v1 training targets. Poison must not become a positive synthesis label.

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
