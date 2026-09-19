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

## Ingest sources

- Hand goldens in `examples/`
- Synthetic single-`define` body rewrites (`scripts/ingest.py`)
- Strand / Unify traces: a round that rebound a name to a **better** body may become a positive sequence. Poison / fitness-drop rounds are not synthesis positives.

`label` on old Strand control traces (`schema/trace.md`) is **not** this `target`. Convert or keep under `examples/legacy-control/`.
