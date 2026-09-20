# orch-pure

Domain: orchestrator-shaped step/route/merge names; pure data, no agents

## High-quality rewrite
step/route/merge over lists. Zero `agent:` `fiber:` `synthesize:` in plant or body.

## Eval assumption
Inputs are small lists or ints; no mailboxes.

## Forbidden tokens
- `eval` in plant or body
- extra `define` inside a rebind body
- `fiber:spawn`, `synthesize:define`
- I/O, shell, network primitives
- control-policy ops (`skip` / `persist` / `restore` / `yield`) as positives
- **zero** `agent:` / `fiber:` / `synthesize:` tokens


## Quota
- Target keep: 3000
- Cap per summary: 250
- Max observe/attempts ratio: 0.6 before adding plants
- Session budget default is smoke (see BUDGET.md); `full` is opt-in

## How Grok Build may extend this catalog
Add plants/rewrites in **this directory only**, same domain, still one `(lambda …)` body.
Re-run `python3 scripts/catalog.py --check --projects --project orch-pure`.
Do not emit free Lisp, do not invent new patch kinds, do not rebind two names in one sample.

## Must not
Do not copy illegal host surfaces. Do not commit `data/raw/`.
Do not call `/loop` or start a second project in the same session.
