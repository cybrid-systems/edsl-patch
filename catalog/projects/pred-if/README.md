# pred-if

Domain: two-arm `if` predicates; both arms must be legal

## High-quality rewrite
Flip or fix branches. Never emit one-arm if. Summaries: flip-branch, always-then, abs-pred, sign.

## Eval assumption
Predicates on ints; both then/else evaluate.

## Forbidden tokens
- `eval` in plant or body
- extra `define` inside a rebind body
- `fiber:spawn`, `synthesize:define`
- I/O, shell, network primitives
- control-policy ops (`skip` / `persist` / `restore` / `yield`) as positives
- one-arm `if` is illegal


## Quota
- Target keep: 3000
- Cap per summary: 250
- Max observe/attempts ratio: 0.6 before adding plants
- Session budget default is smoke (see BUDGET.md); `full` is opt-in

## How Grok Build may extend this catalog
Add plants/rewrites in **this directory only**, same domain, still one `(lambda …)` body.
Re-run `python3 scripts/catalog.py --check --projects --project pred-if`.
Do not emit free Lisp, do not invent new patch kinds, do not rebind two names in one sample.

## Must not
Do not copy illegal host surfaces. Do not commit `data/raw/`.
Do not call `/loop` or start a second project in the same session.
