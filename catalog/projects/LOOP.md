# Continuous farm loop

One **project** per Grok Build session. Default budget is **smoke**.
Do not call `/loop`. Do not pass `--budget full` unless the operator said full.
Do not commit `data/raw/`.

```bash
python3 scripts/farm_loop.py --project arith-core --budget small
```

Status line (last stdout line):

```
FARM_LOOP project=arith-core keep=18 target=20 budget=smoke loops=1 reason=budget
```

`reason` ∈ {quota, budget, wall, max-loop, catalog-exhausted}.

On `catalog-exhausted`, extend **only** `catalog/projects/<id>/` up to `max-catalog-edits`, then:

```
python3 scripts/catalog.py --check --projects --project <id>
python3 scripts/farm_loop.py --project <id> --budget small
```

## Project ids

| id | Domain |
|----|--------|
| `arith-core` | numeric λ |
| `pred-if` | two-arm if |
| `helper-mod` | helper + public |
| `list-fp` | null?/car/cdr/cons |
| `kv-mini` | get/put/default |
| `span-aether` | index/length/clip |
| `circ-dae` | node/edge/eval-node |
| `orch-pure` | step/route/merge (no agent/fiber/synthesize) |
| `twin-step` | frozen integrator + hot control (`--mode world`) |
| `session-hot` | frozen session + hot quote (`--mode world`) |

Dialect projects stay `--mode star`. Verticals use `--mode world`.

## Paste-ready `/goal`

### arith-core
```
/goal Farm project arith-core under budget=small.
Use scripts/farm_loop.py --project arith-core --budget small.
Honor EDSL_PATCH_BUDGET if set; default smoke. Do not pass --budget full unless the operator said full.
If catalog-exhausted, extend catalog/projects/arith-core/ only up to max-catalog-edits, re-check, continue.
Do not touch other projects. Do not commit data/raw. Stop on quota, budget, wall, or max-loop.
```

### pred-if
```
/goal Farm project pred-if under budget=small.
Use scripts/farm_loop.py --project pred-if --budget small.
Honor EDSL_PATCH_BUDGET if set; default smoke. Do not pass --budget full unless the operator said full.
If catalog-exhausted, extend catalog/projects/pred-if/ only up to max-catalog-edits, re-check, continue.
Do not touch other projects. Do not commit data/raw. Stop on quota, budget, wall, or max-loop.
```

### helper-mod
```
/goal Farm project helper-mod under budget=small.
Use scripts/farm_loop.py --project helper-mod --budget small.
Honor EDSL_PATCH_BUDGET if set; default smoke. Do not pass --budget full unless the operator said full.
If catalog-exhausted, extend catalog/projects/helper-mod/ only up to max-catalog-edits, re-check, continue.
Do not touch other projects. Do not commit data/raw. Stop on quota, budget, wall, or max-loop.
```

### list-fp
```
/goal Farm project list-fp under budget=small.
Use scripts/farm_loop.py --project list-fp --budget small.
Honor EDSL_PATCH_BUDGET if set; default smoke. Do not pass --budget full unless the operator said full.
If catalog-exhausted, extend catalog/projects/list-fp/ only up to max-catalog-edits, re-check, continue.
Do not touch other projects. Do not commit data/raw. Stop on quota, budget, wall, or max-loop.
```

### kv-mini
```
/goal Farm project kv-mini under budget=small.
Use scripts/farm_loop.py --project kv-mini --budget small.
Honor EDSL_PATCH_BUDGET if set; default smoke. Do not pass --budget full unless the operator said full.
If catalog-exhausted, extend catalog/projects/kv-mini/ only up to max-catalog-edits, re-check, continue.
Do not touch other projects. Do not commit data/raw. Stop on quota, budget, wall, or max-loop.
```

### span-aether
```
/goal Farm project span-aether under budget=small.
Use scripts/farm_loop.py --project span-aether --budget small.
Honor EDSL_PATCH_BUDGET if set; default smoke. Do not pass --budget full unless the operator said full.
If catalog-exhausted, extend catalog/projects/span-aether/ only up to max-catalog-edits, re-check, continue.
Do not touch other projects. Do not commit data/raw. Stop on quota, budget, wall, or max-loop.
```

### circ-dae
```
/goal Farm project circ-dae under budget=small.
Use scripts/farm_loop.py --project circ-dae --budget small.
Honor EDSL_PATCH_BUDGET if set; default smoke. Do not pass --budget full unless the operator said full.
If catalog-exhausted, extend catalog/projects/circ-dae/ only up to max-catalog-edits, re-check, continue.
Do not touch other projects. Do not commit data/raw. Stop on quota, budget, wall, or max-loop.
```

### orch-pure
```
/goal Farm project orch-pure under budget=small.
Use scripts/farm_loop.py --project orch-pure --budget small.
Honor EDSL_PATCH_BUDGET if set; default smoke. Do not pass --budget full unless the operator said full.
If catalog-exhausted, extend catalog/projects/orch-pure/ only up to max-catalog-edits, re-check, continue.
Do not touch other projects. Do not commit data/raw. Stop on quota, budget, wall, or max-loop.
```

### twin-step
```
/goal Farm project twin-step under budget=small with --mode world.
Use scripts/farm_loop.py --project twin-step --mode world --budget small.
Honor EDSL_PATCH_BUDGET if set; default smoke. Do not pass --budget full unless the operator said full.
If catalog-exhausted, extend catalog/projects/twin-step/ only up to max-catalog-edits, re-check, continue.
Do not rebind step/energy. Do not commit data/raw. Stop on quota, budget, wall, or max-loop.
```

### session-hot
```
/goal Farm project session-hot under budget=small with --mode world.
Use scripts/farm_loop.py --project session-hot --mode world --budget small.
Honor EDSL_PATCH_BUDGET if set; default smoke. Do not pass --budget full unless the operator said full.
If catalog-exhausted, extend catalog/projects/session-hot/ only up to max-catalog-edits, re-check, continue.
Do not rebind *session*. Do not commit data/raw. Stop on quota, budget, wall, or max-loop.
```
