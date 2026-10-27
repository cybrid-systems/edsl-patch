# Sample

One jsonl line = one closed apply-verified pair.

```json
{
  "id": "strand-abs-r4",
  "input": {
    "source": "(define f (lambda (x) x))"
  },
  "target": [
    {"kind": "query", "op": "find", "name": "f"},
    {"kind": "query", "op": "def-use", "name": "f"},
    {
      "kind": "synthesis",
      "op": "rebind",
      "name": "f",
      "body": "(lambda (x) (if (< x 0) (* x -1) x))",
      "summary": "abs"
    }
  ],
  "verify": {
    "apply_ok": true,
    "expected_source": "(define f (lambda (x) (if (< x 0) (* x -1) x)))"
  }
}
```

`target` is the **control patch sequence** to train toward (see `patch.md`).

At train time the prompt is `input.source` plus the legal-op contract. The completion is `target` JSON only.

`verify` stays in working jsonl. `scripts/export_sft.py` strips it.

## v1.5 observe + probes

Commercial verticals add a world observation and optional probes. `expected_source` is **optional** when `probes` is present.

```json
{
  "id": "twin-A1-damp",
  "input": {
    "source": "(define (step w u) w)\n(define (control w) 0)",
    "intent": "oscillation too large; add damping",
    "observe": {
      "t": 40,
      "energy": 12.4,
      "session": {"id": 1, "fd": 7, "alive": true},
      "hot": ["control"],
      "frozen": ["step"],
      "epoch": 3
    }
  },
  "target": [],
  "verify": {
    "apply_ok": true,
    "unchanged": ["step"],
    "expected_source": null,
    "probes": {"t_mono": true, "energy_after_steps_lt": 8.0}
  }
}
```

- `observe.session` may be omitted on twin samples.
- `observe.t` / `energy` may be omitted on session samples.
- `observe.sat` is the saturation count when the plant world has a `sat` key.
- `observe.epoch` is the path-chain hop index (1..depth). Replant only after depth or a probe cut, never mid-hop.
- `observe.session.seq` is present when the session hash threads a sequence number.
- `target` is still a patch array (query + rebind **or** query + refuse), never empty in gold SFT.
- `sft: false` marks apply_ok=false fixtures that must not export.
- Path-mode energy-up refuse golds are sft-true. Observe numbers come from the host, never a hardcoded `12.4` demo.

## Ingest sources

- Hand goldens in `examples/`
- Synthetic single-`define` body rewrites (`scripts/ingest.py`)
- Strand / Unify traces: a round that rebound a name to a **better** body may become a positive sequence. Poison / fitness-drop rounds are not synthesis positives.

`label` on old Strand control traces (`schema/trace.md`) is **not** this `target`. Convert or keep under `examples/legacy-control/`.

## Exported SFT row extras (`scripts/export_sft.py`)

Each `sft.jsonl` row is `{"messages": [system, user, assistant], "difficulty", "test_status", "weight"}`.
Trainers that do not know the extras ignore them; weighted trainers multiply the token loss by `weight`.

- The user prompt drops later whitespace-identical repeats of a top-level `define` (the context
  builder can emit a helper twice) and strips markdown ticks / `**` from the intent. The
  assistant turn is always one JSON patch array (no `<think>`, no fences, no split turns).
- `difficulty`: `query_steps`, `defuse_span` (other context defines that the target calls or that
  call the target), `target_given` (intent names the target, or it is the only define),
  `trivial` (target given and nothing left to explore: span 0, or every query is on the target
  itself), `tier` = trivial | easy (span ≤ 2) | medium (≤ 6) | hard.
- `test_status`: pipeline `verify.test.status` (`pass` | `none` | `no-signal`), `n/a` for rows
  that never had a test stage.
- `weight`: 1.0, ×0.5 for an untested KEEP synthesis (`none` / `no-signal`), ×0.5 for a trivial
  replace. Refuse rows are not down-weighted.
