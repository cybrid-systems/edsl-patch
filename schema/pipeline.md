# Collection pipeline v2

One entry point, one run directory, one report. Rows keep the sample schema
(`schema/sample.md`), so `scripts/export_sft.py` exports them unchanged.

```bash
python3 -m scripts.pipeline selftest                       # pinned host + strict keep gate
python3 -m scripts.pipeline collect \
  --repo ../aura-pad --repo ../aura-redis \
  --out runs/batch1 --intent llm --export                  # every stage, then export if gates pass
python3 -m scripts.pipeline export --out runs/batch1       # re-export later (refuses on a failed gate)
python3 -m scripts.pipeline pin --aura-bin <bin> --write   # pin another build of the same Aura SHA
```

Run from the repo root inside the dev image (`ghcr.io/cybrid-systems/dev:v1.0.9`); the
pinned Aura build needs that image's glibc.

## Stages

| # | Stage | Module | What it does |
|---|-------|--------|--------------|
| 1 | pinned host | `host.py` | `pins/aura-host.json` holds the Aura SHA and allowed binary sha256s. Collection refuses to run when sha256(`AURA_BIN`) is not pinned, when the Aura checkout is at another SHA, or when the self-test fails (plain rebind must be `#t`; an unbound call and an arity mismatch must be rejected). |
| 2 | per-define units | `units.py` | First-parent commits that touch `*.aura`. For each modified non-harness file, diff top-level defines between parent and child. One unit per changed define; units of one commit share `commit_group`. Skipped and counted: comment/whitespace-only, metadata-only (stamp, traj ids, sha/date/version literals), non-lambda defines, unbalanced bodies. Test/case/smoke/fixture files are harness, not units. |
| 3 | closed context | `context.py` | Dependency closure at the parent commit: file-level vars (transitively), direct callees in full, deeper callees as arity stubs, cross-file helpers via the load/require graph (then repo-wide), helpers the same commit adds (child-only, marked in `meta.child_helpers`), up to two callers. Repo `load`/`require` lines are never emitted. The context must load on the pinned host. |
| 4 | apply + tests | `label.py` | Strict apply (`mutate:rebind` returned `#t`) of the parent body (identity control) and the child body on the same context. Identity rejected → closure failure (not a label). Child rejected → ROLLBACK. Cheap Aura tests that load the changed file run on the parent tree and on the parent tree with the child define spliced in; a regression against the parent run → ROLLBACK. Commands and timings are in `verify.test`. |
| 5 | intent | `intent.py` | Per-define intent from the old/new body. `--intent llm` uses MiniMax (`~/.config/aura-build/minimax.env`, key from `MINIMAX_API_KEY_FILE`, never logged) and marks `meta.intent_source=llm`; answers that break a rule fall back to the deterministic template. Banned: score/telemetry lines, model names, personal phrases, CJK, absolute paths, SHAs. |
| 6 | dedup + holdout | `split.py` | Latest 15% of commit groups per repo → eval (no group crosses). Exact dups, conflicting prompts, 5-gram Jaccard ≥ 0.9 near dups dropped; caps per commit (8), per define (4), per change shape (3); eval rows near-duplicate to train dropped. |
| 7 | report + gates | `report.py` | `report.json` / `report.md`: funnel per repo, drop reasons, closure-failure kinds, apply/test rates, KEEP/ROLLBACK, dup/near-dup/conflict, intent sharing and auto lines, lengths, secret and abs-path scans, and export gates. |
| 8 | export | `run.export` | `export_sft.py --profile dialect` on `train.jsonl`, only when every blocking gate passes. |

## Run directory

| File | Content |
|------|---------|
| `units.jsonl` | every unit with its stage, reason, context parts, apply detail, timing |
| `labeled.jsonl` | KEEP and ROLLBACK rows before split/dedup |
| `train.jsonl`, `eval.jsonl` | KEEP rows (sample schema + `verify` + `meta`) |
| `negatives-train.jsonl`, `negatives-eval.jsonl` | ROLLBACK rows, `sft: false`, `verify.apply_ok: false` |
| `report.json`, `report.md` | quality report and gate results |
| `manifest.json` | command, edsl-patch HEAD, repo HEADs, host SHA + binary sha256 + self-test, file sha256s |
| `sft.jsonl`, `sft-manifest.json` | export (only when gates pass) |

## Row

```json
{
  "id": "pv2-…",
  "input": {"source": "<closed context>", "intent": "<per-define intent>"},
  "target": [{"kind": "query", "op": "find", "name": "f"}, {"kind": "query", "op": "def-use", "name": "f"},
             {"kind": "synthesis", "op": "rebind", "name": "f", "body": "(lambda …)", "summary": "…"}],
  "verify": {"apply_ok": true, "label": "KEEP", "reason": "apply-ok+tests", "expected_source": "…",
             "test": {"status": "pass|no-signal|none|regressed", "runs": [{"test": "…", "cmd": "…", "parent": "…", "patched": "…"}]}},
  "meta": {"repo": "…", "file": "…", "name": "f", "parent": "…", "child": "…", "commit_group": "repo@sha12",
           "commit_time": 0, "split": "train", "intent_source": "llm", "child_helpers": [], "context": {},
           "host": "<aura sha>", "host_bin": "<sha256>", "pipeline": "2.0.0"}
}
```

## Closure-failure kinds

- `context-missing`: a repo symbol is not in the context (pipeline bug; gated at ≤ 10%).
- `host-unbound` / `host-arity` / `host-type`: the pinned host's post-mutate typecheck rejects the
  **unchanged** parent body (e.g. `while`, `try`/`catch`, `apply` are unknown to it). These units cannot
  be labeled on this host; the report lists the top symbols.
- `context-too-long`: closure does not fit `MAX_FOCUS_CHARS` after stubbing.
