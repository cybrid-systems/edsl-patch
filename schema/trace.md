# Trace

One jsonl line = one closed-loop round (Strand) or one Unify cycle.

```json
{
  "source": "strand",
  "round": 3,
  "observe": {
    "fitness": 3,
    "fitness_n": 5,
    "source": "(define f (lambda (x) x))",
    "query_find": true,
    "loop_stats_len": 8
  },
  "proposal": {
    "mode": "catalog",
    "body": "(lambda (x) 99)"
  },
  "host": {
    "ok": true,
    "decision": "commit"
  },
  "post": {
    "fitness": 0
  },
  "label": {
    "op": "restore",
    "snap": "heal",
    "why": "fitness 3→0"
  }
}
```

This file is the **legacy Strand/Unify control-trace** shape. v1 training targets are query→synthesis sequences (`schema/patch.md`, `schema/sample.md`), not `skip` / `persist` / `restore`.

Strand fitness traces stay legacy. Do **not** ingest a poison-commit (fitness drop labeled `commit`) as refuse gold — refuse is for frozen/capability/schema, not rollback.

`label` on these traces is a control-policy decision, not the host's raw `decision`. Strand's host often says `commit` on a worse body; the label is still `restore`. Poison-commit rounds are **not** positive synthesis labels.

Ingest (`scripts/ingest.py`):

- A round that rebound a name to a **better** body may become a query + `rebind` sequence.
- Fitness-drop / poison rounds are dropped for v1.
- `.strand/session.aura-soul` is a persist target only, not the patch language.
- Unify `logs/runs/latest/events.jsonl` when the event is an EDSL op.

Committed examples live under `examples/legacy-control/`.
