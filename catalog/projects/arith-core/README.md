# arith-core

Domain: numeric single-arg and two-arg lambdas using + - * / <

## High-quality rewrite
A rewrite is a total numeric function on ints. Prefer two-arm `if` for abs/clamp. Bodies stay one lambda.

## Eval assumption
eval on small integers; no floats required.

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
Re-run `python3 scripts/catalog.py --check --projects --project arith-core`.
Do not emit free Lisp, do not invent new patch kinds, do not rebind two names in one sample.

## Must not
Do not copy illegal host surfaces. Do not commit `data/raw/`.
Do not call `/loop` or start a second project in the same session.
