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
├── lessons/            # teacher seeds (source_0 + source_1 intent)
├── lib/teacher.aura    # namer / binder / helper agents (no mutate)
├── examples/           # apply-verified goldens
├── scripts/            # apply / ingest / teach / export_sft
└── tests/              # legal + apply + teacher fanout
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
python3 scripts/export_sft.py data/raw/verified.jsonl data/raw/teacher.jsonl
```

A `rebind` patch is:

```scheme
(query :find "f")
(mutate:rebind "f" "(lambda (x) (if (< x 0) (* x -1) x))" "abs")
```

Decide / persist / restore stay Strand meanings and are **not** v1 training targets. Poison must not become a positive synthesis label.

## License

Apache License 2.0
