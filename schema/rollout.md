# Rollout — forked-sandbox trajectories

Not star-mode farm. Not Strand control-policy SFT.

Aura already has the pieces: `ast:snapshot` / `ast:restore` (fork),
`agent:spawn` + `agent:ask` (propose only), `mutate:rebind` (single mutator),
`agent:decision-metrics` (engine gate). `fiber:spawn` is **not** the fork —
`lib/teacher.aura` documents CLI closure mis-capture (Aether 12).

```
plant + world_0
  ── snapshot S
        │
        ├─ worker A proposes rebind_1  → restore S → apply → step N → r_1
        ├─ worker B proposes rebind_2  → restore S → apply → step N → r_2
        ├─ worker C proposes refuse    → restore S → no-op  → step N → r_3
        └─ pick argmax r (or keep all r ≥ τ)
             → world_{t+1} becomes next root; hop += 1
```

One JSONL line is either a **hop** (SFT slice) or a **traj** (full tree).

## Hop (SFT / RFT slice)

```json
{
  "id": "roll-twin-h2-damp",
  "kind": "hop",
  "fork_id": "s2b",
  "parent_id": "s2",
  "hop": 2,
  "input": {
    "source": "…",
    "intent": "energy 14.2→8.1 at t=80; keep damping",
    "observe": {"t": 80, "energy": 8.1, "sat": 2, "hot": ["control"], "frozen": ["step", "energy"], "epoch": 2}
  },
  "target": [{"kind": "query", "op": "find", "name": "control"}, {"kind": "synthesis", "op": "rebind", "name": "control", "body": "(lambda (world) (* -1 (hash-ref world \"v\")))", "summary": "damp-v"}],
  "reward": {"r": 1.7, "advantage": 0.9, "components": {"energy": 1.4, "t_mono": 0.2, "sat": 0.1, "contract": 0.0}},
  "verify": {"apply_ok": true, "unchanged": ["step", "energy"], "probes": {"t_mono": true}}
}
```

`input.observe` is **measured**. `advantage` = r − mean(r of siblings at this fork).
`export_sft.py --profile commercial` ingests `data/raw/rollout-*.jsonl` hops only
(`kind=hop`, `sft=true`, `advantage>0`). Drop `kind=traj`, identity-cut / t_break,
and kill-alive hops. Twin/session hops count toward the 40/20 vertical buckets,
not dialect. Prompt includes measured `input.observe` + `intent`.

## Traj (debug / GRPO group)

```json
{
  "id": "roll-twin-traj-7",
  "kind": "traj",
  "project": "twin-step",
  "hops": ["roll-twin-h1-…", "roll-twin-h2-…"],
  "return": 3.1,
  "cut": "depth|reward|metrics-back-off|identity"
}
```

## Reward (host, not LLM)

See `catalog/rewards/*.json`. Twin default:

- −10 if `t` not monotonic; −20 if frozen source changed
- `+5 * (e0-e1)/max(e0, ε)` energy drop (clip [−5, 5])
- `−3` if sat increment > N/2
- `+2` refuse when energy rose or metrics say back-off
- `−2` rebind when energy rose
- session: `−20` if alive/fd/id change; `−5` seq jump; `+1` identity hold

Engine `agent:decision-metrics` recommendation `escalate`/`back-off`
cuts the chain. That cut is a **refuse** gold if observe worsened, not a `restore` positive.

## Workers vs mutator

| Role | Aura surface | May mutate? |
|------|----------------|-------------|
| namer / binder / catalog sampler | `agent:ask` | no |
| reward host | Python `scripts/rollout.py` | no |
| mutator | `mutate:rebind` once per fork | yes, one name ∈ hot |

Do not train `restore` / `skip` / `yield` as targets. Snapshot restore is the **sandbox implementation**, not the label.

## CLI

```bash
python3 scripts/rollout.py --project twin-step --depth 6 --forks 4 --rounds 8
python3 scripts/rollout.py --host aura --project twin-step --depth 1 --forks 2 --rounds 1 --plant mass-spring
python3 -m unittest tests.test_rollout_reward -v
```

`--host dry-world` (default) runs the in-process Python stepper (no Aura binary) so rewards
and tree cuts can be tested. `--host aura` plants, `ast:snapshot`s, rebinds, and steps via
`lib/sandbox.aura` (`EDSL_OBS`). Snapshot restore is plumbing, never an SFT `restore` label.
`--host aura` without a binary exits 2. No `fiber:spawn`.
