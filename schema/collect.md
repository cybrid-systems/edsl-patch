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

Cursor: `data/raw/collect-cursor.json` is tracked with the other `data/raw/` jsonl. Already-seen sample ids are not appended twice.

A candidate is kept only if `scripts/apply.py` succeeds on a **closed excerpt** of the parent file: the changed define, def-use neighbors, and callee signatures (≤12000 characters). Apply does not put the sibling worktree on `AURA_PATH`, so `expected_source` is the host print of that excerpt.

`input.intent` is the child commit subject, plus the first paragraph of the body when it adds detail, prefixed with the define name. `summary` is that subject as a short phrase, not `name@sha`.

Dropped before apply:

- stamp / trajectory metadata (`stamp-info`, `self_evolve_stamp`, `traj_id`)
- comment-only or whitespace-only body edits
- a body that calls a helper defined only on the child commit
- unbalanced `rebind` bodies
- excerpts that contain `/workspace/` or `/home/` paths
- the same focused prompt mapped to more than one body

```bash
python3 scripts/collect.py --rewrite --dry-run   # classify the current business jsonl
python3 scripts/collect.py --rewrite             # reshape it in place, then re-apply
python3 scripts/collect.py --reverify            # drop rows whose rebind is not #t; rewrite expected_source
```
