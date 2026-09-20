# twin-step

Live-twin vertical: step the **same** world, rebind only `control`, never the integrator.

## Plants (inequivalent `step`)

| id | World keys | Energy | Expected probe fails |
|----|------------|--------|----------------------|
| `mass-spring` | x v t | x²+v² | `zero-u`/`hold` (no dissipation) |
| `sat-plant` | x v t sat | x²+v²+sat | `sign-damp` (|u|=2 bang-bang raises sat) |
| `push-obs` | x v t | x²+v² | needs recover after frozen `impulse` kick every 10 ticks |
| `two-mass` | x1 v1 x2 v2 t | both masses | `p-x` on x1 only can heat x2 |

`step` bodies are pairwise distinct. Do not clone Euler.

## Integrator contract

- `step` maps `(world, u) → world` and increments `t` by 1.
- `sat-plant` clips `u` to [−1,1] **inside step** and counts clips on `sat`.
- `push-obs` frozen helper `impulse` adds +2 to `v` when `t` is a multiple of 10.
- Initial `control` is weak (0).

## High-quality rewrite

After N=40 pre/post steps, **all** of the following must hold (`scripts/farm.py` `twin_should_keep`):

- `t1 == t0 + N_post`
- rebind name ∈ hot, not frozen (`step` / `energy` / `impulse`)
- `energy_post < energy_pre` (strict)
- if world has `sat`: `sat_post ≤ sat_pre + N_post/2` (bang-bang fails this)
- two-mass: `|x2|_post ≤ max(|x2|_pre, 20)`

Expected drops (not refuse gold): `sign-damp` on `sat-plant`; `zero-u`/`hold` on mass-spring (noop vs plant control, or energy does not fall); apply-fail. Do not lower probes to raise keep rate.

## Forbidden

- rebind `step` / `energy` / `impulse`
- `eval`, extra `define` in body, `fiber:spawn`, `synthesize:define`

## Quota

1500 keep. cap-per-summary 200. Default budget smoke.

## Extend

Add plants only with a **new** `step` body. `names` = `hot` = `[control]`.
