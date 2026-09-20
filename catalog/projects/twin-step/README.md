# twin-step

Live-twin vertical: step the **same** world, rebind only `control`, never the integrator.

## High-quality rewrite

`control` maps a world hash → scalar `u`. After rebind, `N=40` steps of
`(step world (control world))` must raise `t` by 40 and drop energy (`x^2+v^2`)
versus the pre-patch controller. Frozen `step` / `energy` stay byte-identical.

## Eval assumption

World is a hash with `x`, `v`, `t`. `step` is `(world, u) → world` and increments `t` by 1.
Farm later runs 40 steps pre and post. No I/O.

## Integrator contract

- `step` maps `(world, u) → world` and increments `t` by 1.
- `energy` is read-only: `x^2 + v^2`.
- Initial `control` is weak (0 / tiny gain), not already optimal.

## Forbidden

- rebind `step` or `energy`
- tokens `eval`, `define` in body, `fiber:spawn`, `synthesize:define`, `c-load`
- I/O, sockets, Isaac/FIX

## Probes (farm later)

- `t_mono`: t increases by N_post
- energy drop or `|x|` drop
- `verify.unchanged` includes `step` and `energy`

## Quota

1500 keep (not 3000). cap-per-summary 200. Session budget default smoke; `full` is opt-in.

## How Grok Build may extend

Add plants/rewrites **in this directory only**. Still one `(lambda …)` body.
`names` must equal `hot`. Re-run `python3 scripts/catalog.py --check --projects --project twin-step`.
Do not invent skip/persist/restore golds. Do not commit `data/raw/`.
