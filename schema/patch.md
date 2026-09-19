# Control patch

One model output = one patch. JSON object. No markdown, no `<think>` in the trained target (strip at ingest).

```json
{
  "op": "rebind",
  "name": "f",
  "body": "(lambda (x) (if (< x 0) (* x -1) x))",
  "summary": "abs"
}
```

## Legal `op`

| `op` | Fields | Host |
|------|--------|------|
| `rebind` | `name` string, `body` Aura lambda string, `summary` string | `agent:closed-loop-once :rebind` / `edsl-fix` |
| `skip` | `reason` string | no mutate; Strand back-off / `mutate:safe-yield` |
| `persist` | `path` string | `persist:save` only after fitness gain |
| `restore` | `snap` int or `"heal"` | `ast:restore` / `hot-strategy:heal!` |
| `yield` | (none) | `mutate:safe-yield` |

Anything else (raw `eval`, extra defines, shell, `fiber:spawn`) is **illegal**. Train to refuse, not to emit.

## `body` (rebind only)

- One `(lambda …)` form.
- Two-arm `if` when `if` is used.
- No `<think>`, no ` ``` `, no extra top-level `define`.

## Decision after apply

The model does **not** emit `commit` / `rollback` as host truth. The host still `agent:decide`s. Training labels:

- `rebind` that drops fitness → target should have been `restore` or not-rebind.
- poison body → `restore`.
- fitness gain → `persist` allowed on the next step.
