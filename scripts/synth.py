#!/usr/bin/env python3
"""Hybrid-Gym style synthetic tasks on closed Aura contexts (P1 pilot).

Pool: contexts that already closed on the pinned host (pipeline train/eval rows).
Per picked define D (a define-fn with at least one in-context callee):

  locate  intent describes D without naming it; gold = find D, def-use D, rebind D
          (body kept, leading plan comment). Judge: completion names D + host apply ok.
  deps    intent names D, asks for one def-use per direct callee; gold set = callees of D
          defined in the context (static, Jedi-like). Judge: def-use set == gold + apply ok.
  fill    D's body is a hole `(lambda (params) #f)`; intent describes D. Judge: host
          strict apply (typecheck gate) ok; `exact` also records whether the body is
          comment/whitespace-equivalent to the original.

A teacher LLM (OpenAI-compatible MiniMax endpoint) proposes the patch; Aura gates are
the rejection-sampling filter. Accepted rows are edsl-patch samples (input/target/verify/meta).
The API key is read by pipeline.intent.load_minimax and never logged.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sys
import subprocess
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from apply import apply_patch, apply_succeeded, run_aura_program  # noqa: E402
from edsl_patch import ILLEGAL_HINTS, SYSTEM_CONTRACT, PatchError, validate_patch  # noqa: E402
from export_sft import dedupe_context  # noqa: E402
from parse_aura import bodies_equivalent, code_symbols, lambda_param_form, lambda_params, patch_for  # noqa: E402
from pipeline.intent import load_minimax  # noqa: E402
from pipeline.context import RepoIndex, build_context  # noqa: E402
from pipeline.label import load_check  # noqa: E402
from pipeline.report import ABS  # noqa: E402
from pipeline.units import is_harness, ls_aura, top_forms  # noqa: E402
from parse_aura import MAX_FOCUS_CHARS  # noqa: E402

TASKS = ("locate", "deps", "fill")
DEFAULT_MODEL = "MiniMax-M3.1-Flash"

DESCRIBE = """Language: Aura (a Scheme dialect). Here is one function definition:

{form}

Write ONE sentence (max 35 words) describing what this function computes and how, so a programmer
could find it in a large file or re-implement it. Do NOT write its name, and do not quote code.
Answer with the sentence only."""


def _usage_add(acc: dict, data: dict) -> None:
    u = data.get("usage") or {}
    acc["prompt_tokens"] = acc.get("prompt_tokens", 0) + int(u.get("prompt_tokens") or 0)
    acc["completion_tokens"] = acc.get("completion_tokens", 0) + int(u.get("completion_tokens") or 0)
    acc["calls"] = acc.get("calls", 0) + 1


def chat(cfg: dict, messages: list[dict], usage: dict, *, max_tokens: int = 8000, temperature: float = 0.2) -> tuple[str, float]:
    body = {"model": cfg["model"], "messages": messages, "max_tokens": max_tokens, "temperature": temperature}
    t0 = time.time()
    for attempt in range(3):
        try:
            req = urllib.request.Request(
                cfg["base"] + "/chat/completions",
                data=json.dumps(body).encode(),
                headers={"Authorization": "Bearer " + cfg["_key"], "Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=240) as resp:
                data = json.load(resp)
            _usage_add(usage, data)
            text = data["choices"][0]["message"]["content"] or ""
            return re.sub(r"(?s)<think>.*?</think>", "", text).strip(), time.time() - t0
        except Exception:  # noqa: BLE001 - network / API: retry, then give up
            time.sleep(2 * (attempt + 1))
    return "", time.time() - t0


def parse_array(text: str):
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    i, j = t.find("["), t.rfind("]")
    if i < 0 or j < i:
        raise PatchError("no JSON array")
    return json.loads(t[i : j + 1])


def candidates(rows: list[dict], min_body: int, max_body: int) -> list[dict]:
    seen: set[str] = set()
    out = []
    for row in rows:
        src = dedupe_context(row["input"]["source"])
        forms = top_forms(src)
        names = {f.name for f in forms if f.kind == "define-fn" and f.name}
        for f in forms:
            if f.kind != "define-fn" or not f.name or not f.body.lstrip().startswith("(lambda"):
                continue
            if not (min_body <= len(f.body) <= max_body):
                continue
            # A gold body the contract forbids (eval, fences, ...) can never pass the gate.
            if any(tok in f.body for tok in ILLEGAL_HINTS):
                continue
            key = " ".join(f.text.split())
            if key in seen:
                continue
            # Direct callees: in-context define-fn names used in the body (globals excluded).
            callees = sorted((code_symbols(f.body) & names) - {f.name})
            if not callees:
                continue
            seen.add(key)
            out.append({"source": src, "name": f.name, "body": f.body, "form": f.text, "start": f.start, "end": f.end,
                        "callees": callees, "origin": row.get("id"),
                        "repo": ((row.get("meta") or {}).get("repo"))})
    return out


def _cand_from_context(text: str, name: str, body: str, origin: str, repo: str) -> dict | None:
    forms = top_forms(text)
    names = {f.name for f in forms if f.kind == "define-fn" and f.name}
    for f in forms:
        if f.name == name and f.kind == "define-fn":
            callees = sorted((code_symbols(f.body) & names) - {name})
            if not callees:
                return None
            return {"source": text, "name": name, "body": f.body, "form": f.text, "start": f.start, "end": f.end,
                    "callees": callees, "origin": origin, "repo": repo}
    return None


def repo_candidates(repo: Path, cap: int, seed: int, min_body: int, max_body: int, workers: int) -> tuple[list[dict], dict]:
    """Closed single-define contexts at repo HEAD; identity rebind must pass the host gate."""
    sha = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    idx = RepoIndex.build(repo, sha)
    raw = []
    for rel in sorted(idx.files):
        if is_harness(rel):
            continue
        for f in idx.files[rel]:
            if f.kind != "define-fn" or not f.name or not f.body.lstrip().startswith("(lambda"):
                continue
            if not (min_body <= len(f.body) <= max_body) or any(t in f.body for t in ILLEGAL_HINTS) or ABS.search(f.body):
                continue
            raw.append((rel, f))
    random.Random(seed).shuffle(raw)
    stats = {"repo": repo.name, "head": sha, "defines": len(raw), "tried": 0, "closed": 0, "drop": {}}
    out: list[dict] = []
    lock = threading.Lock()

    def drop(why: str) -> None:
        with lock:
            stats["drop"][why] = stats["drop"].get(why, 0) + 1

    def one(item):
        rel, f = item
        with lock:
            if len(out) >= cap:
                return
            stats["tried"] += 1
        ctx = build_context(idx, rel, f.name, f.text, f.body, f.body, {}, MAX_FOCUS_CHARS)
        if ctx.text is None:
            return drop(ctx.reason)
        if ABS.search(ctx.text):
            return drop("abs-path")
        text = dedupe_context(ctx.text)
        c = _cand_from_context(text, f.name, f.body, f"{repo.name}@{sha[:12]}:{rel}", repo.name)
        if c is None:
            return drop("no-callee")
        ok, _why = load_check(text)
        if not ok:
            return drop("context-load")
        try:
            if not apply_succeeded(apply_patch(text, patch_for(f.name, f.body, "identity"), timeout=60)):
                return drop("identity-reject")
        except PatchError:
            return drop("identity-error")
        with lock:
            if len(out) < cap:
                out.append(c)
                stats["closed"] += 1

    # Chunked so the cap stops work early.
    for i in range(0, len(raw), max(workers * 4, 1)):
        if len(out) >= cap:
            break
        with ThreadPoolExecutor(workers) as ex:
            list(ex.map(one, raw[i : i + workers * 4]))
    return out[:cap], stats


# Differential behavior gate for fill: same context, original vs filled define, same probe calls.
PROFILES = {
    "int": ["0", "1", "2", "-1", "5", "10", "97"],
    "str": ['""', '"a"', '"ab c"', '"hello"', '"x1"'],
    "list": ["(list)", "(list 1 2 3)", "(list \"a\" \"b\")", "(list 0)"],
    "mixed": ["0", "3", '"a"', '""', "(list 1 2)", "(list)", "#t", "#f"],
}
PROBES_PER_PROFILE = 6


def probe_program(source: str, name: str, nparams: int, profile: str, watch: list[str]) -> str:
    vals = PROFILES[profile]
    rng = random.Random(f"{name}:{profile}")
    calls = []
    seen = set()
    for k in range(PROBES_PER_PROFILE):
        args = tuple(vals[(k + j) % len(vals)] if profile != "mixed" else rng.choice(vals) for j in range(nparams))
        if args in seen:
            continue
        seen.add(args)
        calls.append("(" + " ".join((name,) + args) + ")")
    lines = [source.strip()]
    for i, call in enumerate(calls):
        lines.append(f'(display "@@{i} ") (display (try {call} (catch (e) "ERR"))) (newline)')
        for w in watch:
            lines.append(f'(display "@@{i} {w}=") (display {w}) (newline)')
    return "\n".join(lines) + "\n"


def _probe_out(src: str) -> list[str] | None:
    try:
        out = run_aura_program(src, timeout=20)
    except PatchError:
        return None
    lines = [l for l in out.splitlines() if l.startswith("@@")]
    return lines or None


def behavior_gate(c: dict, filled_body: str, fill_src: str) -> dict:
    """pass: >=1 profile ran on the original with a non-ERR result and every profile that ran
    printed identical lines for both; fail: any difference; no-signal: nothing comparable."""
    params = lambda_params(c["body"])
    if re.search(r"\(lambda\s+[^\s(]", c["body"]) or "." in lambda_param_form(c["body"]).split():
        return {"status": "no-signal", "why": "variadic"}
    nparams = len(lambda_param_form(c["body"]).strip("()").split())
    var_names = {f.name for f in top_forms(c["source"]) if f.kind == "define-var"}
    watch = sorted(var_names & code_symbols(c["body"]))[:6]
    filled_src = fill_src.replace(
        f"(define {c['name']} (lambda {lambda_param_form(c['body'])} #f))", f"(define {c['name']} {filled_body})", 1
    )
    runs = []
    for prof in PROFILES if nparams else ["int"]:
        a = _probe_out(probe_program(c["source"], c["name"], nparams, prof, watch))
        if a is None:
            runs.append({"profile": prof, "status": "orig-failed"})
            continue
        b = _probe_out(probe_program(filled_src, c["name"], nparams, prof, watch))
        useful = any(not l.endswith(" ERR") for l in a if "=" not in l.split(" ", 1)[0])
        if b != a:
            diff = next((i for i, (x, y) in enumerate(zip(a, b or [])) if x != y), None)
            runs.append({"profile": prof, "status": "diff", "first": (a[diff] if diff is not None else "")[:120],
                         "got": ((b or [""])[diff] if diff is not None and b else "")[:120]})
        else:
            runs.append({"profile": prof, "status": "same" if useful else "same-all-err"})
    st = [r["status"] for r in runs]
    status = "fail" if "diff" in st else "pass" if "same" in st else "no-signal"
    return {"status": status, "runs": runs, "params": nparams, "watch": watch}


def leaks_name(text: str, name: str) -> bool:
    return re.search(r"(?<![\w:*!?<>=/+-])" + re.escape(name) + r"(?![\w:*!?<>=/+-])", text) is not None


# One worked example appended to the contract: the teacher must emit kind+op on every step.
EXAMPLE = (
    'Example answer: [{"kind":"query","op":"find","name":"f"},{"kind":"query","op":"def-use","name":"g"},'
    '{"kind":"synthesis","op":"rebind","name":"f","body":"(lambda (x) (g x))","summary":"why"}]'
)


def task_prompt(task: str, c: dict, desc: str) -> tuple[str, str]:
    if task == "locate":
        src = c["source"]
        intent = (
            f"Locate the define that does this: {desc} Then rebind it with its body unchanged except for a "
            "leading ; comment that states how you would extend or harden it."
        )
    elif task == "deps":
        src = c["source"]
        intent = (
            f"Find every define in this file that {c['name']} calls directly. Emit find {c['name']}, then one "
            f"def-use query per directly called define, then rebind {c['name']} with its body unchanged except "
            "for a leading ; comment listing those defines."
        )
    else:
        hole = f"(define {c['name']} (lambda {lambda_param_form(c['body'])} #f))"
        src = c["source"][: c["start"]] + hole + c["source"][c["end"] :]
        intent = f"Implement {c['name']} (its body is a stub): {desc}"
    return src, intent


def judge(task: str, c: dict, patch: list[dict], src: str, timeout: int) -> dict:
    v: dict = {"schema_ok": False, "apply_ok": False, "pass": False}
    try:
        validate_patch(patch)
    except PatchError as e:
        v["reason"] = "schema:" + str(e)[:80]
        return v
    v["schema_ok"] = True
    last = patch[-1]
    if last.get("kind") != "synthesis" or last.get("op") != "rebind":
        v["reason"] = "not-rebind"
        return v
    if task in ("locate", "deps") and last["name"] != c["name"]:
        v["reason"] = "wrong-target"
        return v
    if task == "deps":
        got = sorted({s["name"] for s in patch[:-1] if s.get("op") == "def-use"} - {c["name"]})
        v["deps_got"] = got
        if got != c["callees"]:
            v["reason"] = "deps-mismatch"
            return v
    if task in ("locate", "deps") and not bodies_equivalent(last["body"], c["body"]):
        v["reason"] = "body-changed"
        return v
    try:
        res = apply_patch(src, patch, timeout=timeout)
        v["apply_ok"] = apply_succeeded(res)
        if not v["apply_ok"]:
            det = (res.get("synthesis") or {}).get("detail")
            v["reason"] = "host-reject:" + json.dumps(det)[:160]
            return v
    except PatchError as e:
        v["reason"] = "host-error:" + str(e)[:120]
        return v
    if task == "fill":
        v["exact"] = bodies_equivalent(last["body"], c["body"])
        if last["name"] != c["name"]:
            v["reason"] = "wrong-target"
            return v
        bg = {"status": "pass", "why": "exact"} if v["exact"] else behavior_gate(c, last["body"], src)
        v["behavior"] = bg
        if bg["status"] == "fail":
            v["reason"] = "behavior-diff"
            return v
    v["pass"] = True
    return v


def _test_of(task: str, v: dict) -> dict:
    """locate/deps keep the body, so the host gate is the whole check; fill carries the behavior gate."""
    if task != "fill":
        return {"status": "pass", "runs": [], "kind": "body-unchanged"}
    bg = v.get("behavior") or {}
    return {"status": bg.get("status", "none"), "runs": bg.get("runs", []), "kind": "differential"}


def run_one(cfg: dict, c: dict, tasks: tuple[str, ...], timeout: int, usage: dict) -> list[dict]:
    out = []
    desc, dt = chat(cfg, [{"role": "user", "content": DESCRIBE.format(form=c["form"][:4000])}], usage, temperature=0.2)
    desc = " ".join(desc.replace("`", "").split())
    if not desc or leaks_name(desc, c["name"]):
        return [{"task": t, "name": c["name"], "verify": {"pass": False, "reason": "describe-failed"}, "latency": dt} for t in tasks]
    for task in tasks:
        src, intent = task_prompt(task, c, desc)
        user = src.strip() + "\nintent: " + intent
        text, lat = chat(
            cfg,
            [{"role": "system", "content": SYSTEM_CONTRACT.strip() + "\n" + EXAMPLE}, {"role": "user", "content": user}],
            usage,
            max_tokens=16000,
        )
        try:
            patch = parse_array(text)
            v = judge(task, c, patch, src, timeout)
        except (PatchError, json.JSONDecodeError, TypeError) as e:
            patch, v = None, {"pass": False, "schema_ok": False, "reason": "parse:" + str(e)[:80]}
        rid = "syn-" + task + "-" + hashlib.sha256((c["form"] + task).encode()).hexdigest()[:12]
        out.append({
            "id": rid,
            "task": task,
            "name": c["name"],
            "repo": c.get("repo"),
            "latency": round(lat + (dt if task == tasks[0] else 0), 2),
            "verify": v,
            "raw": text[-4000:],
            "sample": {
                "id": rid,
                "input": {"source": src, "intent": intent},
                "target": patch,
                "verify": {"apply_ok": v.get("apply_ok", False), "label": "KEEP" if v.get("pass") else "DROP",
                           "test": _test_of(task, v), "synth": v},
                "meta": {"synth_task": task, "name": c["name"], "gold_callees": c["callees"], "origin": c["origin"],
                         "teacher": cfg["model"], "gold_body": c["body"], "repo": c.get("repo")},
            },
        })
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("pool", nargs="*", type=Path, help="pipeline rows (train/eval jsonl) whose contexts closed on the host")
    p.add_argument("--repo", action="append", type=Path, default=[], help="Aura repo checkout: build closed contexts at HEAD")
    p.add_argument("--per-repo-cap", type=int, default=60)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--n", type=int, default=20, help="defines to sample")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--tasks", default=",".join(TASKS))
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--timeout", type=int, default=60)
    p.add_argument("--min-body", type=int, default=80)
    p.add_argument("--max-body", type=int, default=1500)
    args = p.parse_args(argv)
    cfg = load_minimax()
    if not cfg:
        print("synth: no MiniMax config", file=sys.stderr)
        return 2
    cfg["model"] = args.model
    rows = [json.loads(l) for path in args.pool for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    pool = candidates(rows, args.min_body, args.max_body)
    pool_stats = []
    t_pool = time.time()
    for repo in args.repo:
        got, st = repo_candidates(repo, args.per_repo_cap, args.seed, args.min_body, args.max_body, args.workers)
        print("synth: pool " + json.dumps(st), flush=True)
        pool += got
        pool_stats.append(st)
    pool_sec = round(time.time() - t_pool, 1)
    n_pool = len(pool)
    random.Random(args.seed).shuffle(pool)
    cands = pool[: args.n]
    tasks = tuple(t for t in args.tasks.split(",") if t in TASKS)
    usage: dict = {}
    t0 = time.time()
    with ThreadPoolExecutor(args.workers) as ex:
        results = [r for rs in ex.map(lambda c: run_one(cfg, c, tasks, args.timeout, usage), cands) for r in rs]
    args.out.mkdir(parents=True, exist_ok=True)
    with (args.out / "attempts.jsonl").open("w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with (args.out / "accepted.jsonl").open("w", encoding="utf-8") as f:
        for r in results:
            if r["verify"].get("pass"):
                f.write(json.dumps(r["sample"], ensure_ascii=False) + "\n")
    summary = {"model": cfg["model"], "pool_candidates": n_pool, "pool_sec": pool_sec, "pool_repos": pool_stats,
               "defines": len(cands), "wall_sec": round(time.time() - t0, 1), "usage": usage, "tasks": {}}
    for t in tasks:
        rs = [r for r in results if r["task"] == t]
        reasons: dict[str, int] = {}
        for r in rs:
            if not r["verify"].get("pass"):
                k = str(r["verify"].get("reason", "?")).split(":")[0]
                reasons[k] = reasons.get(k, 0) + 1
        lat = sorted(r["latency"] for r in rs)
        summary["tasks"][t] = {
            "n": len(rs),
            "schema_ok": sum(1 for r in rs if r["verify"].get("schema_ok")),
            "pass": sum(1 for r in rs if r["verify"].get("pass")),
            "exact": sum(1 for r in rs if r["verify"].get("exact")),
            "fail_reasons": reasons,
            "latency_p50": lat[len(lat) // 2] if lat else None,
        }
    for t in tasks:
        summary["tasks"][t]["by_repo"] = {}
        for r in results:
            if r["task"] != t:
                continue
            b = summary["tasks"][t]["by_repo"].setdefault(str(r.get("repo")), {"n": 0, "pass": 0})
            b["n"] += 1
            b["pass"] += 1 if r["verify"].get("pass") else 0
        if t == "fill":
            beh: dict[str, int] = {}
            for r in results:
                if r["task"] == "fill" and "behavior" in r["verify"]:
                    k = r["verify"]["behavior"]["status"]
                    beh[k] = beh.get(k, 0) + 1
            summary["tasks"][t]["behavior"] = beh
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
