# Apply

Host apply is offline. No LLM. Sibling checkout, same parent as Strand:

```text
../aura-grok/build/aura
AURA_PATH=../aura-grok/lib
AURA_SANDBOX=off
```

```bash
python3 scripts/apply.py --sample examples/identity-to-abs.jsonl
```

## Driver

`scripts/apply.py` writes a throwaway Aura program, runs it on stdin, parses one JSON result line prefixed with `EDSL_PATCH_RESULT `.

1. `(set-code source_0)` then `(eval-current)`
2. Each query op: eval, record `{op, ok, empty}`
3. `(ast:snapshot "edsl-patch")` then synthesis (`mutate:rebind` or `synthesize:fill`)
4. `(eval-current)`; on failure `(ast:restore)`
5. Print post-source via `(current-source)`

```json
{
  "ok": true,
  "query": [{"op": "find", "ok": true, "empty": false}],
  "synthesis": {"op": "rebind", "ok": true},
  "source": "(define f (lambda (x) (if (< x 0) (* x -1) x)))"
}
```

Query payloads do not include raw node ids. Verify uses: query `ok`, `find` not empty for the rebind name, post-source matches expected (whitespace-tolerant).

## Probes (v1.5)

After a successful **rebind**, the host may run world probes instead of (or in addition to) `expected_source`:

- **twin**: `N` steps of `(step world (control world))`; `t` monotonic; optional `energy_after_steps_lt`; frozen names unchanged.
- **session**: `*session*` id/fd/alive unchanged; `(quote book)` returns numbers.
- **refuse**: do **not** `mutate:rebind`; source/world identical; `apply_ok` true.

## Keep / drop

Keep a sample when:

- sequence is legal (`schema/patch.md`)
- apply `ok` is true
- post-source matches `verify.expected_source`, or an optional fitness table passes

Drop poison rebinds that lower fitness. Those are not v1 synthesis labels.
