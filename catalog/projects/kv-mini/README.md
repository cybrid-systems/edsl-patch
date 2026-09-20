# kv-mini

Domain: Unify-KV *shape*: get/put/default as pure functions over lists/pairs

## High-quality rewrite
Names get/put/miss/default. Bodies are lambdas over alists. No I/O, no evolve, no journal.

## Eval assumption
box is a list of (key . val) pairs; keys comparable with equal?.

Rollout probes (`catalog/rewards/kv-mini.json`): get looks up fixture `((1 . 10))` (hit then miss); put must cons `(1 . 10)` onto `'()`; miss is `#f` on nonempty and `#t` on empty. Hops export as dialect.

## Forbidden tokens
- `eval` in plant or body
- extra `define` inside a rebind body
- `fiber:spawn`, `synthesize:define`
- I/O, shell, network primitives
- control-policy ops (`skip` / `persist` / `restore` / `yield`) as positives
- no file/net primitives
- no unify journal / persist


## Quota
- Target keep: 3000
- Cap per summary: 250
- Max observe/attempts ratio: 0.6 before adding plants
- Session budget default is smoke (see BUDGET.md); `full` is opt-in

## How Grok Build may extend this catalog
Add plants/rewrites in **this directory only**, same domain, still one `(lambda …)` body.
Re-run `python3 scripts/catalog.py --check --projects --project kv-mini`.
Do not emit free Lisp, do not invent new patch kinds, do not rebind two names in one sample.

## Must not
Do not copy illegal host surfaces. Do not commit `data/raw/`.
Do not call `/loop` or start a second project in the same session.
