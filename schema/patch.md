# Patch sequence

One model output = one JSON **array**. No markdown, no `<think>` in the trained target (strip at ingest).

v1 sequence: **≥1 query, then exactly one synthesis**. Query never mutates. Synthesis is the only mutate.

```json
[
  {"kind": "query", "op": "find", "name": "f"},
  {"kind": "query", "op": "def-use", "name": "f"},
  {
    "kind": "synthesis",
    "op": "rebind",
    "name": "f",
    "body": "(lambda (x) (if (< x 0) (* x -1) x))",
    "summary": "abs"
  }
]
```

Compile to host:

```scheme
(query :find "f")
(query :def-use "f")
(mutate:rebind "f" "(lambda (x) (if (< x 0) (* x -1) x))" "abs")
```

## Sequence rules

1. First ops are `kind: query`. Last op is `kind: synthesis`. No other kinds.
2. Query args are **name-based**. Never emit raw node ids (unstable across host runs). Query *results* belong in apply `observe`, not in the target.
3. `rebind.body` is one `(lambda …)` form. Two-arm `if` when `if` is used. No extra top-level `define`.
4. Extra JSON keys are illegal.

## Legal `query` ops

Host: `(query :op …)`.

| `op` | Fields | Host |
|------|--------|------|
| `find` | `name` string | `(query :find name)` |
| `def-use` | `name` string | `(query :def-use name)` |
| `root` | (none) | `(query :root)` |

`find` must return a non-empty locus when the synthesis `name` is that symbol.

Deferred (need stable-ref): `:children`, `:parent`, `:node`.

## Legal `synthesis` ops

| `op` | Fields | Host |
|------|--------|------|
| `rebind` | `name` string, `body` Aura lambda string, `summary` string | `(mutate:rebind name body summary)` |
| `fill` | `template` string, `args` list of strings | `(synthesize:fill template args…)` |

`rebind` is the default. `fill` is allowed only if that template is already registered in the apply session. v1 goldens use `rebind` only.

Apply uses the primitive directly. Do **not** route through `agent:decide` / `edsl-fix` (those can skip or rollback a valid labeled patch). Do **not** emit `synthesize:define` (nested LLM).

## Illegal

Train to refuse, not to emit:

- raw `eval`, extra top-level `define`, shell, `fiber:spawn`
- `synthesize:define` / `synthesize:pipeline`
- control-policy ops as v1 targets: `skip`, `persist`, `restore`, `yield`, `heal`
- node-id query fields
- more than one synthesis, or synthesis before query

Control-policy ops stay a later track. Strand poison-commit traces are **not** positive synthesis labels.
