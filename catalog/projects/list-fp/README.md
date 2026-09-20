# list-fp

Domain: list recursion with null? car cdr cons

## High-quality rewrite
Small quoted lists. Rewrites stay structural (empty, first, rest, cons-1). Do not mutate helper+caller in one sample.

## Eval assumption
Quoted lists of ints, e.g. (quote (1 2 3)).

Rollout probes (`catalog/rewards/list-fp.json`): empty vs `(5 6)` for len/head; tail encodes `(null? . car)`; wrap(7) encodes `(nonempty . car)`. Plants are already the structural golds, so refuse beats vacuous empties. Hops export as dialect.

## Forbidden tokens
- `eval` in plant or body
- extra `define` inside a rebind body
- `fiber:spawn`, `synthesize:define`
- I/O, shell, network primitives
- control-policy ops (`skip` / `persist` / `restore` / `yield`) as positives


## Quota
- Target keep: 3000
- Cap per summary: 250
- Max observe/attempts ratio: 0.6 before adding plants
- Session budget default is smoke (see BUDGET.md); `full` is opt-in

## How Grok Build may extend this catalog
Add plants/rewrites in **this directory only**, same domain, still one `(lambda …)` body.
Re-run `python3 scripts/catalog.py --check --projects --project list-fp`.
Do not emit free Lisp, do not invent new patch kinds, do not rebind two names in one sample.

## Must not
Do not copy illegal host surfaces. Do not commit `data/raw/`.
Do not call `/loop` or start a second project in the same session.
