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

`label` is the **control patch** to train toward, not the host's raw `decision`. Strand's host often says `commit` on a worse body; the label is still `restore`.

Ingest from:

- Strand stdout (`R3 … fitness 3→0`, `rollback fitness now=3`)
- `.strand/session.aura-soul` only as persist target, not as the patch language
- Unify `logs/runs/latest/events.jsonl` when the event is an EDSL op
