# Continuous collection

Training data from **real sibling Aura programs**, not toy abs/double.

## Sources

| Source | What | How it keeps growing |
|--------|------|----------------------|
| `git` | Consecutive commits that changed a named `define` | New Unify / span commits |
| `live --identity` | Current bodies restated as rebind | Optional; query practice on real names |
| Unify journal | Generation cursor | Bodies still come from git of `projects/kv` |

Plant of record: Unify in-memory KV (`unify/projects/kv`) — load-adaptive engine, 148-test smoke floor, accepted evolve generations.

## Run

```bash
# incremental; safe to re-run
python3 scripts/collect.py

# after a Unify evolve cycle
cd ../unify && ./scripts/evolve.sh   # or wait for overnight
cd ../edsl-patch && python3 scripts/collect.py

python3 scripts/export_sft.py data/raw/business.jsonl data/raw/teacher.jsonl
```

Cursor: `data/raw/collect-cursor.json` (gitignored). Already-seen sample ids are not appended twice.

A candidate is kept only if `scripts/apply.py` succeeds on the **parent file** with `query + mutate:rebind` of the child body.
