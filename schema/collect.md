# Continuous collection

Training data from **real sibling Aura programs**, not toy abs/double.

## Sources

| Source | What | How it keeps growing |
|--------|------|----------------------|
| `git` | Consecutive commits that changed a named `define` | New Unify / span commits |
| `live --identity` | Current bodies restated as rebind | Optional; query practice on real names |
| Unify journal | Generation cursor | Bodies still come from git of `projects/kv` |

Plant of record: Unify in-memory KV (`unify/projects/kv`) — load-adaptive engine, 148-test smoke floor, accepted evolve generations.

## Layout

`scripts/collect.py` looks for sibling repos **next to** `edsl-patch`:

```text
../aura-grok/build/aura     # or $AURA_BIN
../aura-grok/lib            # or $AURA_LIB
../unify ../aether ../daedalus ../hephaestus ../prometheus ../hermes ../flux
```

`--limit` caps **git candidates before apply** (default: budget `collect_limit`, smoke=5).

## Run

```bash
python3 scripts/collect.py --doctor          # diagnosis only; no jsonl
python3 scripts/collect.py --limit 5         # incremental apply-verified harvest

# after a Unify evolve cycle
cd ../unify && ./scripts/evolve.sh
cd ../edsl-patch && python3 scripts/collect.py --limit 5

python3 scripts/export_sft.py data/raw/business.jsonl data/raw/teacher.jsonl
```

Cursor: `data/raw/collect-cursor.json` (gitignored). Already-seen sample ids are not appended twice.

A candidate is kept only if `scripts/apply.py` succeeds on the **parent file** with `query + mutate:rebind` of the child body.
