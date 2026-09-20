# twin-step

Live-twin vertical: step the **same** world, rebind only `control`, never the integrator.

## Plants (inequivalent `step`)

| id | World keys | Energy | Expected probe fails |
|----|------------|--------|----------------------|
| `mass-spring` | x v t | x²+v² | `zero-u`/`hold` (no dissipation) |
| `sat-plant` | x v t sat | x²+v²+sat | `sign-damp` (bang-bang raises sat) |
| `push-obs` | x v t | x²+v² | needs recover after frozen `impulse` kick every 10 ticks |
| `two-mass` | x1 v1 x2 v2 t | both masses | `p-x` on x1 only can heat x2 |

`step` bodies are pairwise distinct. Do not clone Euler.

## Integrator contract

- `step` maps `(world, u) → world` and increments `t` by 1.
- `sat-plant` clips `u` to [−1,1] **inside step** and counts clips on `sat`.
- `push-obs` frozen helper `impulse` adds +2 to `v` when `t` is a multiple of 10.
- Initial `control` is weak (0).

## High-quality rewrite

After N=40 pre/post steps, energy must **strictly** fall, `t` monotonic, frozen pretty-source unchanged. `sign-damp` on sat-plant must **drop**.

## Forbidden

- rebind `step` / `energy` / `impulse`
- `eval`, extra `define` in body, `fiber:spawn`, `synthesize:define`

## Quota

1500 keep. cap-per-summary 200. Default budget smoke.

## Extend

Add plants only with a **new** `step` body. `names` = `hot` = `[control]`.
