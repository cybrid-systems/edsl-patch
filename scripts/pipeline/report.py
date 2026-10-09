"""Stage 7: quality report (JSON + Markdown) and export gates."""

from __future__ import annotations

import json
import re
import statistics
from collections import Counter
from pathlib import Path

from edsl_patch import PatchError, validate_patch
from parse_aura import MAX_FOCUS_CHARS

from .intent import AUTO_LINE, CJK, MODEL_NAMES, PERSONAL, violations
from .split import completion_text, jaccard, prompt_text, shingles, NEAR_DUP_J

SECRET = re.compile(
    r"sk-[A-Za-z0-9_-]{16,}|AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{30,}|-----BEGIN [A-Z ]*PRIVATE KEY|"
    r"(?i:api[_-]?key|secret|password|token)\s*[=:]\s*['\"][^'\"\s]{12,}['\"]|eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}"
)
ABS = re.compile(r"/(?:workspace|home|Users|root)/[\w.-]+|[A-Z]:\\\\")


def _dist(xs: list[int]) -> dict:
    if not xs:
        return {"n": 0}
    s = sorted(xs)
    q = lambda p: s[min(len(s) - 1, int(p * (len(s) - 1) + 0.5))]  # noqa: E731
    return {"n": len(s), "min": s[0], "p50": q(0.5), "p90": q(0.9), "max": s[-1], "mean": round(statistics.mean(s), 1)}


def _tok(s: str) -> int:
    return max(1, len(s) // 3)


def text_of(row: dict) -> str:
    return json.dumps(row, ensure_ascii=False)


def scan_rows(rows: list[dict]) -> dict:
    n = len(rows)
    out: dict = {"n": n}
    if not n:
        return out
    prompts = [prompt_text(r) for r in rows]
    comps = [completion_text(r) for r in rows]
    pairs = Counter(zip(prompts, comps))
    out["exact_dup_rows"] = sum(c - 1 for c in pairs.values() if c > 1)
    byp: dict[str, set] = {}
    for p, c in zip(prompts, comps):
        byp.setdefault(p, set()).add(c)
    out["conflict_rows"] = sum(1 for p in prompts if len(byp[p]) > 1)
    sh = [shingles(p + "\n" + c) for p, c in zip(prompts, comps)]
    nd = set()
    for i in range(n):
        for j in range(i + 1, n):
            if jaccard(sh[i], sh[j]) >= NEAR_DUP_J:
                nd.add(j)
    out["near_dup_rows"] = len(nd)
    intents = [str((r.get("input") or {}).get("intent") or "") for r in rows]
    ic = Counter(intents)
    out["intent_shared_rows"] = sum(c for t, c in ic.items() if c > 1)
    out["intent_auto_line_rows"] = sum(1 for t in intents if AUTO_LINE.search(t))
    out["intent_model_name_rows"] = sum(1 for t in intents if MODEL_NAMES.search(t))
    out["intent_personal_rows"] = sum(1 for t in intents if PERSONAL.search(t) or CJK.search(t))
    out["intent_violation_rows"] = sum(1 for t in intents if violations(t))
    out["intent_mentions_name_rows"] = sum(
        1 for r, t in zip(rows, intents) if (r.get("meta") or {}).get("name", "\x00") in t
    )
    out["intent_source"] = dict(Counter((r.get("meta") or {}).get("intent_source", "?") for r in rows))
    out["secret_rows"] = sum(1 for r in rows if SECRET.search(text_of(r)))
    out["abs_path_rows"] = sum(
        1 for r, t in zip(rows, intents) if ABS.search((r.get("input") or {}).get("source", "") + completion_text(r) + t)
    )
    bad_schema = 0
    for r in rows:
        try:
            validate_patch(r.get("target"))
        except PatchError:
            bad_schema += 1
    out["schema_invalid_rows"] = bad_schema
    out["source_too_long_rows"] = sum(1 for r in rows if len((r.get("input") or {}).get("source", "")) > MAX_FOCUS_CHARS)
    out["expected_eq_input_rows"] = sum(1 for r in rows if (r.get("meta") or {}).get("prints_same"))
    out["prompt_chars"] = _dist([len(p) for p in prompts])
    out["prompt_tokens_est"] = _dist([_tok(p) for p in prompts])
    out["target_tokens_est"] = _dist([_tok(c) for c in comps])
    out["per_repo"] = dict(Counter((r.get("meta") or {}).get("repo") for r in rows))
    cg = Counter((r.get("meta") or {}).get("commit_group") for r in rows)
    out["commit_groups"] = len(cg)
    out["max_rows_per_commit"] = max(cg.values())
    out["multi_unit_commit_rows"] = sum(c for c in cg.values() if c > 1)
    out["test"] = dict(Counter(((r.get("verify") or {}).get("test") or {}).get("status", "none") for r in rows))
    return out


GATES = [
    # (name, level, check(report) -> (ok, value))
    ("train-nonempty", "block", lambda R: (R["train"]["n"] > 0, R["train"]["n"])),
    ("train-size>=200", "warn", lambda R: (R["train"]["n"] >= 200, R["train"]["n"])),
    ("host-pinned+selftest", "block", lambda R: (bool(R["host"].get("selftest", {}).get("ok")), R["host"].get("bin_sha256", "")[:12])),
    ("schema-valid", "block", lambda R: (R["train"].get("schema_invalid_rows", 0) == 0, R["train"].get("schema_invalid_rows", 0))),
    ("train-all-keep-strict", "block", lambda R: (R["train_labels"].get("ROLLBACK", 0) == 0, R["train_labels"])),
    ("secrets==0", "block", lambda R: (R["all"].get("secret_rows", 0) == 0, R["all"].get("secret_rows", 0))),
    ("abs-paths==0", "block", lambda R: (R["all"].get("abs_path_rows", 0) == 0, R["all"].get("abs_path_rows", 0))),
    ("exact-dup==0", "block", lambda R: (R["train"].get("exact_dup_rows", 0) == 0, R["train"].get("exact_dup_rows", 0))),
    ("conflicts==0", "block", lambda R: (R["train"].get("conflict_rows", 0) == 0, R["train"].get("conflict_rows", 0))),
    ("near-dup<=2%", "block", lambda R: (R["train"].get("near_dup_rows", 0) <= 0.02 * max(1, R["train"]["n"]), R["train"].get("near_dup_rows", 0))),
    ("expected==input==0", "block", lambda R: (R["train"].get("expected_eq_input_rows", 0) == 0, R["train"].get("expected_eq_input_rows", 0))),
    ("intent-auto-lines==0", "block", lambda R: (R["all"].get("intent_auto_line_rows", 0) == 0, R["all"].get("intent_auto_line_rows", 0))),
    ("intent-model/personal==0", "block", lambda R: (R["all"].get("intent_model_name_rows", 0) + R["all"].get("intent_personal_rows", 0) == 0, R["all"].get("intent_model_name_rows", 0) + R["all"].get("intent_personal_rows", 0))),
    ("intent-shared<=5%", "block", lambda R: (R["train"].get("intent_shared_rows", 0) <= 0.05 * max(1, R["train"]["n"]), R["train"].get("intent_shared_rows", 0))),
    ("source<=MAX_FOCUS_CHARS", "block", lambda R: (R["train"].get("source_too_long_rows", 0) == 0, R["train"].get("source_too_long_rows", 0))),
    ("no-commit-group-crosses-split", "block", lambda R: (R["split_cross_groups"] == 0, R["split_cross_groups"])),
    ("eval-nonempty", "warn", lambda R: (R["eval"]["n"] > 0, R["eval"]["n"])),
    ("closure-failure(context)<=10%", "block", lambda R: (R["rates"]["closure_failure_context"] <= 0.10, R["rates"]["closure_failure_context"])),
    ("closure-failure(all)<=30%", "warn", lambda R: (R["rates"]["closure_failure"] <= 0.30, R["rates"]["closure_failure"])),
    ("tested-share>=30%", "warn", lambda R: (R["rates"]["keep_tested_share"] >= 0.30, R["rates"]["keep_tested_share"])),
    ("max-rows-per-commit<=8", "block", lambda R: (R["train"].get("max_rows_per_commit", 0) <= 8, R["train"].get("max_rows_per_commit", 0))),
]


def evaluate_gates(R: dict) -> list[dict]:
    out = []
    for name, level, fn in GATES:
        try:
            ok, val = fn(R)
        except Exception as e:  # noqa: BLE001
            ok, val = False, f"error: {e}"
        out.append({"gate": name, "level": level, "ok": bool(ok), "value": val})
    return out


def gates_pass(gates: list[dict]) -> bool:
    return all(g["ok"] for g in gates if g["level"] == "block")


def write_markdown(R: dict, path: Path) -> None:
    L = []
    L.append(f"# Pipeline v2 quality report — `{R['run_id']}`\n")
    L.append(
        f"- edsl-patch: `{R['manifest']['edsl_patch_head'][:12]}`; pipeline {R['manifest']['pipeline_version']}, "
        f"code sha256 `{R['manifest'].get('pipeline_code_sha256', '')[:16]}…`"
    )
    L.append(f"- host: Aura `{R['host']['aura_sha'][:12]}`, bin sha256 `{R['host']['bin_sha256'][:16]}…`, self-test {'OK' if R['host'].get('selftest', {}).get('ok') else 'FAIL'}")
    for repo, m in R["manifest"]["repos"].items():
        L.append(f"- repo `{repo}` @ `{m['head'][:12]}` ({m['remote']})")
    L.append(f"- intents: {R['manifest']['intent_mode']}")
    L.append("")
    L.append("## Funnel per repo\n")
    cols = ["commits_scanned", "commits_with_units", "units", "closure_ok", "identity_ok", "apply_ok", "prints_same", "host_reject", "KEEP", "ROLLBACK", "after_dedup", "train", "eval", "train_neg", "eval_neg"]
    L.append("| repo | " + " | ".join(cols) + " |")
    L.append("|---" * (len(cols) + 1) + "|")
    for repo, f in R["funnel"].items():
        L.append(f"| {repo} | " + " | ".join(str(f.get(c, 0)) for c in cols) + " |")
    L.append("")
    L.append("## Drop / skip reasons\n")
    for k, v in sorted(R["drops"].items(), key=lambda kv: -kv[1]):
        L.append(f"- {k}: {v}")
    L.append("")
    L.append("## Rates\n")
    for k, v in R["rates"].items():
        L.append(f"- {k}: {v}")
    L.append("")
    L.append(f"- closure failure kinds: {R.get('closure_fail_kinds')}")
    L.append(f"- host typecheck: unbound symbols that the repo does not define (top): {R.get('host_unbound_symbols_top')}")
    L.append("")
    L.append("## Labels\n")
    L.append(f"- all: {R['labels']}")
    L.append(f"- ROLLBACK reasons: {R['rollback_reasons']}")
    L.append(f"- KEEP test status: {R['keep_test_status']}")
    L.append("")
    for part in ("train", "eval", "all"):
        s = R[part]
        L.append(f"## {part} (n={s['n']})\n")
        if not s["n"]:
            continue
        for k in ("exact_dup_rows", "near_dup_rows", "conflict_rows", "intent_shared_rows", "intent_auto_line_rows", "intent_violation_rows", "intent_mentions_name_rows", "intent_source", "secret_rows", "abs_path_rows", "schema_invalid_rows", "expected_eq_input_rows", "commit_groups", "max_rows_per_commit", "multi_unit_commit_rows", "per_repo", "test", "prompt_chars", "prompt_tokens_est", "target_tokens_est"):
            if k in s:
                L.append(f"- {k}: {s[k]}")
        L.append("")
    L.append("## Export gates\n")
    L.append("| gate | level | ok | value |\n|---|---|---|---|")
    for g in R["gates"]:
        L.append(f"| {g['gate']} | {g['level']} | {'PASS' if g['ok'] else 'FAIL'} | {g['value']} |")
    L.append("")
    L.append(f"**Export allowed: {'yes' if R['export_allowed'] else 'no'}**\n")
    path.write_text("\n".join(L) + "\n", encoding="utf-8")
