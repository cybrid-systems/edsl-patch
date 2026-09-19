# edsl-patch

**Post-training for Aura EDSL control patches.** Not a Unify span. Not a Strand loop.

Strand *runs* one O→D→M→V→R loop as a program. This repo *trains a model to emit the control patch* that loop applies — structured EDSL ops, not a free Lisp essay.

```
observe  (query, fitness, loop-stats, current-source)
    →  control patch
         rebind | skip | persist | restore | heal | yield
    →  apply on Aura  (agent:closed-loop-once / edsl-fix / decide)
    →  reward  (fitness, rollback-correct, persist-durable)
```

## What this is

| In | Out |
|----|-----|
| Closed-loop trace from [Strand](https://github.com/cybrid-systems/strand) / [Unify](https://github.com/cybrid-systems/unify) | One **control patch** |
| Host: [Aura](https://github.com/cybrid-systems/aura) `std/agent` EDSL | Ops `edsl-fix` / `agent:closed-loop-once` already know |

A patch is a small JSON object (see `schema/patch.md`). The only legal `op` values are the EDSL controls. A lambda body is allowed **only** as the argument of `rebind`, never as the whole answer.

## What this is not

- Not Aura (language/host).
- Not Strand (the seed that produces traces).
- Not Unify (live MiniMax evolve + issue pump).
- Not `ai-programming-language-design` (philosophy).
- Weights and raw dumps stay out of git (`checkpoints/`, `data/raw/`).

## Layout

```text
edsl-patch/
├── schema/patch.md     # legal ops
├── schema/trace.md     # Strand/Unify → jsonl
├── examples/           # one golden trace + patch
└── README.md
```

Trainer and eval land here when there is a script. Until then the contract is the schema.

## Apply (host)

Sibling checkouts, same parent as Strand:

```text
../aura-grok/build/aura
../strand/loop.aura
```

A `rebind` patch is:

```scheme
(agent:closed-loop-once
  :skip-set-code
  :rebind name body
  :summary "edsl-patch")
```

Decide / persist / restore stay the Strand meanings: commit only if fitness does not drop; poison must not stick.

## License

Apache License 2.0
