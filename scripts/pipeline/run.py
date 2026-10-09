"""Orchestration: one `collect` run over one or more repos."""

from __future__ import annotations

import hashlib
import re
import json
import shlex
import subprocess
import sys
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from edsl_patch import PatchError, validate_patch
from parse_aura import patch_for

from . import PIPELINE_VERSION, ROOT
from .context import RepoIndex, build_context, child_helper_forms
from .host import Host
from .intent import load_minimax, make_intent, template_intent
from .label import TreeCache, discover_tests, load_check, run_unit_tests, strict_apply
from .report import ABS, evaluate_gates, gates_pass, scan_rows, write_markdown
from .split import cap, dedup, holdout, leak_filter
from .units import Unit, list_commits, ls_aura, split_commit


def log(msg: str) -> None:
    print(f"[pipeline {time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


def git_out(repo: Path, *args: str) -> str:
    try:
        return subprocess.check_output(["git", "-C", str(repo), *args], text=True, stderr=subprocess.DEVNULL).strip()
    except (subprocess.CalledProcessError, OSError):
        return ""


def repo_name_of(repo: Path) -> str:
    url = git_out(repo, "config", "--get", "remote.origin.url")
    name = url.rstrip("/").rsplit("/", 1)[-1] if url else repo.name
    return name[:-4] if name.endswith(".git") else name


class IndexCache:
    def __init__(self):
        self._d: dict[tuple[str, str], RepoIndex] = {}
        self._locks: dict[tuple[str, str], threading.Lock] = defaultdict(threading.Lock)
        self._g = threading.Lock()

    def get(self, repo: Path, sha: str) -> RepoIndex:
        key = (str(repo), sha)
        with self._g:
            lk = self._locks[key]
        with lk:
            if key not in self._d:
                self._d[key] = RepoIndex.build(repo, sha)
            return self._d[key]


def summary_of(name: str, old_body: str, new_body: str) -> str:
    text = template_intent(name, old_body, new_body)
    text = text.removeprefix(f"Change {name} to ").rstrip(".")
    if len(text) > 60:
        text = text[:60].rsplit(" ", 1)[0]
    return text or "update"


_UNBOUND = re.compile(r"unbound variable: ([^\s;]+)")


_CALLEE = re.compile(r"call '([^']+)'")


def repo_symbols(pidx: RepoIndex, helpers: dict) -> set[str]:
    syms: set[str] = set(helpers)
    for f in pidx.files:
        syms |= set(pidx.defines(f))
    return syms


def host_only_reject(detail: str, category: str, repo_syms: set[str]) -> bool:
    """A rejection that names only symbols the repo does not define (e.g. `try`,
    variadic `string-append`) is a limit of the host typecheck, not a bad patch."""
    if category not in ("unbound", "arity"):
        return False
    named = set(_UNBOUND.findall(detail)) | set(_CALLEE.findall(detail))
    named = {n.rstrip("\\n") for n in named}
    return bool(named) and not (named & repo_syms)


def identity_reason(ar, pidx: RepoIndex, helpers: dict) -> str:
    """Why the parent body itself was rejected on the closed context.

    context-missing  a symbol defined in the repo is not in the context (our bug)
    host-unbound     a symbol the repo does not define (a host primitive such as
                     `while`) is unknown to the post-mutate typecheck
    host-arity/type  the host typecheck rejects the unchanged parent body
    """
    if ar.category in ("arity", "type"):
        return f"identity-host-{ar.category}"
    if ar.category != "unbound":
        return f"identity-{ar.category or 'error'}"
    syms = set(_UNBOUND.findall(ar.detail))
    repo_syms: set[str] = set(helpers)
    for f in pidx.files:
        repo_syms |= set(pidx.defines(f))
    if syms & repo_syms:
        return "identity-context-missing"
    return "identity-host-unbound"


def process_unit(u: Unit, repo: Path, host: Host, idx: IndexCache, trees: TreeCache, opts: dict) -> dict:
    """Run stages 3-4 for one unit. Returns a result record (always)."""
    rec: dict = {"unit": u, "stage": "", "reason": "", "row": None, "timing": {}}
    t0 = time.time()
    if ABS.search(u.new_body) or ABS.search(u.old_body):
        rec.update(stage="skip", reason="abs-path-in-body")
        return rec
    try:
        validate_patch(patch_for(u.name, u.new_body, "x"))
        validate_patch(patch_for(u.name, u.old_body, "x"))
    except PatchError as e:
        rec.update(stage="skip", reason="illegal-token" if "illegal token" in str(e) else "schema")
        rec["detail"] = str(e)[:200]
        return rec
    pidx = idx.get(repo, u.parent)
    helpers = {}
    if u.info.get("added_refs"):
        cidx = idx.get(repo, u.child)
        added = set()
        for f in cidx.files:
            added |= set(cidx.defines(f))
        for f in pidx.files:
            added -= set(pidx.defines(f))
        helpers = child_helper_forms(cidx, added, u.new_body, u.name)
    ctx = build_context(pidx, u.file, u.name, u.old_form, u.old_body, u.new_body, helpers, opts["budget"])
    rec["context"] = ctx.parts
    rec["timing"]["context"] = round(time.time() - t0, 2)
    if ctx.text is None:
        rec.update(stage="closure-fail", reason=ctx.reason)
        return rec
    if ABS.search(ctx.text):
        # Repo-absolute paths in helper code become repo-relative; the target body is never rewritten.
        rel_txt = re.sub(r"/workspace/" + re.escape(u.repo) + r"/", "", ctx.text)
        ctx.parts["abs_paths_rewritten"] = len(re.findall(r"/workspace/" + re.escape(u.repo) + r"/", ctx.text))
        if ABS.search(rel_txt):
            rec.update(stage="skip", reason="abs-path-in-context")
            return rec
        ctx.text = rel_txt
    t1 = time.time()
    ok, why = load_check(ctx.text)
    rec["timing"]["load"] = round(time.time() - t1, 2)
    if not ok:
        rec.update(stage="closure-fail", reason="context-load", detail=why[:400])
        return rec
    summary = summary_of(u.name, u.old_body, u.new_body)
    ar = strict_apply(ctx.text, u.name, u.old_body, u.new_body, summary)
    rec["timing"]["apply"] = round(ar.sec, 2)
    rec["apply"] = {"ident_ok": ar.ident_ok, "ok": ar.ok, "category": ar.category, "detail": ar.detail[:400], "error": ar.error}
    if ar.category == "illegal-token":
        rec.update(stage="skip", reason="illegal-token")
        return rec
    if not ar.ident_ok:
        rec.update(stage="closure-fail", reason=identity_reason(ar, pidx, helpers), detail=ar.detail[:400])
        return rec
    if ar.ok and ar.prints_same:
        rec.update(stage="skip", reason="prints-same")
        return rec
    test = {"status": "none", "runs": []}
    if ar.ok and opts["tests"]:
        ls = ls_aura(repo, u.parent)
        tests = discover_tests(repo, u.parent, u.file, ls)
        if tests:
            tl = run_unit_tests(trees, repo, opts["repo_names"][str(repo)], u, tests, [h.text for h in helpers.values()])
            test = {"status": tl.status, "runs": tl.runs, "sec": round(tl.sec, 2)}
            rec["timing"]["tests"] = round(tl.sec, 2)
    if not ar.ok and host_only_reject(ar.detail, ar.category, repo_symbols(pidx, helpers)):
        rec.update(stage="host-reject", reason=f"child-host-{ar.category}", detail=ar.detail[:400])
        return rec
    if not ar.ok:
        label, reason = "ROLLBACK", f"rejected-{ar.category}"
        named = {n.rstrip("\\n") for n in set(_UNBOUND.findall(ar.detail)) | set(_CALLEE.findall(ar.detail))}
        if named & set(u.info.get("commit_changed", [])):
            reason += "-coupled"
    elif test["status"] == "regressed":
        label, reason = "ROLLBACK", "test-regressed"
    else:
        label, reason = "KEEP", "apply-ok" + ("+tests" if test["status"] == "pass" else "")
    row = {
        "id": u.id,
        "input": {"source": ctx.text},
        "target": patch_for(u.name, u.new_body, summary),
        "verify": {
            "apply_ok": bool(ar.ok and label == "KEEP"),
            "label": label,
            "reason": reason,
            "expected_source": ar.source if ar.ok else None,
            "reject_detail": ar.detail[:400] if not ar.ok else "",
            "test": test,
            "apply_cmd": "python3 scripts/apply.py --sample <row>  (strict: mutate:rebind returned #t)",
            "apply_sec": round(ar.sec, 2),
        },
        "meta": {
            "repo": u.repo,
            "file": u.file,
            "name": u.name,
            "parent": u.parent,
            "child": u.child,
            "commit_group": u.commit_group,
            "commit_time": u.commit_time,
            "old_body": u.old_body,
            "context": ctx.parts,
            "child_helpers": sorted(helpers),
            "label": label,
            "prints_same": False,
            "host": host.aura_sha,
            "host_bin": host.bin_sha256,
            "pipeline": PIPELINE_VERSION,
        },
    }
    if label == "ROLLBACK":
        row["sft"] = False
    rec.update(stage="labeled", reason=reason, row=row)
    rec["timing"]["total"] = round(time.time() - t0, 2)
    return rec


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def code_sha256() -> str:
    """Digest of the pipeline code and host pin, independent of commit SHAs."""
    h = hashlib.sha256()
    files = sorted((ROOT / "scripts" / "pipeline").glob("*.py")) + [ROOT / "pins" / "aura-host.json"]
    for p in files:
        h.update(str(p.relative_to(ROOT)).encode() + b"\0" + p.read_bytes() + b"\0")
    return h.hexdigest()


def write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def collect(repos: list[Path], out: Path, host: Host, opts: dict, argv: list[str]) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    started = time.time()
    host.activate()
    trees = TreeCache(out / ".trees", host.env())
    idx = IndexCache()
    opts["repo_names"] = {str(r): repo_name_of(r) for r in repos}
    manifest = {
        "pipeline_version": PIPELINE_VERSION,
        "edsl_patch_head": git_out(ROOT, "rev-parse", "HEAD"),
        "edsl_patch_dirty": bool(git_out(ROOT, "status", "--porcelain", "--", "scripts", "pins")),
        "pipeline_code_sha256": code_sha256(),
        "command": "python3 -m scripts.pipeline " + " ".join(shlex.quote(a) for a in argv),
        "host": host.as_manifest(),
        "repos": {},
        "options": {k: v for k, v in opts.items() if k != "repo_names"},
        "started": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    funnel: dict[str, Counter] = {}
    drops: Counter = Counter()
    all_units: list[tuple[Unit, Path]] = []
    for repo in repos:
        name = opts["repo_names"][str(repo)]
        manifest["repos"][name] = {
            "path": str(repo),
            "head": git_out(repo, "rev-parse", "HEAD"),
            "remote": git_out(repo, "config", "--get", "remote.origin.url"),
        }
        commits = list_commits(repo, max_commits=opts.get("max_commits"))
        counts: dict[str, int] = {}
        units: list[Unit] = []
        for c in commits:
            units += split_commit(repo, name, c, counts, child_helpers=opts["child_helpers"])
        f = Counter()
        f["commits_scanned"] = len(commits)
        f["commits_with_units"] = len({u.commit_group for u in units})
        f["units"] = len(units)
        f["units_with_child_helpers"] = sum(1 for u in units if u.info.get("added_refs"))
        funnel[name] = f
        for k, v in counts.items():
            drops[f"{name}:{k}"] += v
        all_units += [(u, repo) for u in units]
        log(f"{name}: {len(commits)} commits -> {len(units)} units")
    if opts.get("max_units"):
        all_units = all_units[: opts["max_units"]]

    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=opts["workers"]) as ex:
        futs = [ex.submit(process_unit, u, repo, host, idx, trees, opts) for u, repo in all_units]
        for i, fu in enumerate(futs, 1):
            try:
                results.append(fu.result())
            except Exception as e:  # noqa: BLE001
                u = all_units[i - 1][0]
                results.append({"unit": u, "stage": "error", "reason": f"{type(e).__name__}: {e}"[:300], "row": None})
            if i % 10 == 0 or i == len(futs):
                log(f"units {i}/{len(futs)}")

    rows: list[dict] = []
    unit_log = []
    for r in results:
        u: Unit = r["unit"]
        f = funnel[u.repo]
        st, why = r["stage"], r["reason"]
        if st != "skip" or why == "prints-same":
            pass
        if st == "skip":
            drops[f"{u.repo}:skip:{why}"] += 1
            if why == "prints-same":
                f["prints_same"] += 1
                f["closure_ok"] += 1
                f["identity_ok"] += 1
                f["apply_ok"] += 1
        elif st == "closure-fail":
            drops[f"{u.repo}:closure-fail:{why}"] += 1
            f["closure_fail"] += 1
        elif st == "host-reject":
            drops[f"{u.repo}:host-reject:{why}"] += 1
            f["closure_ok"] += 1
            f["identity_ok"] += 1
            f["host_reject"] += 1
        elif st == "error":
            drops[f"{u.repo}:error"] += 1
        elif st == "labeled":
            f["closure_ok"] += 1
            f["identity_ok"] += 1
            if r["apply"]["ok"]:
                f["apply_ok"] += 1
            f[r["row"]["verify"]["label"]] += 1
            rows.append(r["row"])
        unit_log.append(
            {
                "id": u.id, "repo": u.repo, "file": u.file, "name": u.name, "commit_group": u.commit_group,
                "stage": st, "reason": why, "detail": r.get("detail", ""), "apply": r.get("apply"),
                "context": r.get("context"), "timing": r.get("timing"), "added_refs": u.info.get("added_refs", []),
            }
        )
    write_jsonl(out / "units.jsonl", unit_log)

    # Stage 5: intents
    cfg = load_minimax(Path(opts["minimax_env"]) if opts.get("minimax_env") else None) if opts["intent"] == "llm" else None
    if opts["intent"] == "llm" and cfg is None:
        log("intent=llm but MiniMax config/key not found; using templates")
    intent_rejects: Counter = Counter()

    def do_intent(row: dict) -> None:
        m = row["meta"]
        text, src, bad = make_intent(m["name"], m["file"], m["old_body"], row["target"][-1]["body"], cfg)
        row["input"]["intent"] = text
        m["intent_source"] = src
        for b in bad:
            intent_rejects[b] += 1

    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(do_intent, rows))
    manifest["intent_mode"] = f"{opts['intent']}" + (f" ({cfg['model']} @ {cfg['base']})" if cfg else "")
    manifest["intent_llm_rejected"] = dict(intent_rejects)
    write_jsonl(out / "labeled.jsonl", rows)

    # Stage 6: holdout by repo/time, then dedup within each split
    rows.sort(key=lambda r: (r["meta"]["commit_time"], r["id"]))
    split = holdout(rows, opts["eval_share"])
    for r in rows:
        r["meta"]["split"] = split[r["meta"]["commit_group"]]
    keep = [r for r in rows if r["verify"]["label"] == "KEEP"]
    neg = [r for r in rows if r["verify"]["label"] == "ROLLBACK"]
    sdrops: Counter = Counter()
    train = cap(dedup([r for r in keep if r["meta"]["split"] == "train"], sdrops), sdrops)
    ev = dedup([r for r in keep if r["meta"]["split"] == "eval"], sdrops)
    ev = leak_filter(train, ev, sdrops)
    ndrops: Counter = Counter()
    train_neg = dedup([r for r in neg if r["meta"]["split"] == "train"], ndrops)
    eval_neg = dedup([r for r in neg if r["meta"]["split"] == "eval"], ndrops)
    for k, v in sdrops.items():
        drops[f"dedup:{k}"] += v
    for k, v in ndrops.items():
        drops[f"dedup-neg:{k}"] += v
    for part, rs in (("train", train), ("eval", ev), ("train_neg", train_neg), ("eval_neg", eval_neg)):
        for r in rs:
            funnel[r["meta"]["repo"]][part] += 1
    for name, f in funnel.items():
        f["after_dedup"] = f["train"] + f["eval"]
    write_jsonl(out / "train.jsonl", train)
    write_jsonl(out / "eval.jsonl", ev)
    write_jsonl(out / "negatives-train.jsonl", train_neg)
    write_jsonl(out / "negatives-eval.jsonl", eval_neg)

    # Stage 7: report
    tot = Counter()
    for f in funnel.values():
        tot.update(f)
    closable = tot["closure_ok"] + tot["closure_fail"]
    keep_n = tot["KEEP"]
    keep_tested = sum(1 for r in keep if r["verify"]["test"]["status"] == "pass")
    train_groups = {r["meta"]["commit_group"] for r in train + train_neg}
    eval_groups = {r["meta"]["commit_group"] for r in ev + eval_neg}
    cf = Counter()
    host_syms = Counter()
    for r in results:
        if r["stage"] == "closure-fail":
            why = r["reason"]
            cf["host" if "-host-" in why else ("budget" if why == "context-too-long" else "context")] += 1
            if why == "identity-host-unbound":
                for s_ in set(_UNBOUND.findall(r.get("detail", ""))):
                    host_syms[s_.rstrip("\\n")] += 1
    R = {
        "run_id": out.name,
        "closure_fail_kinds": dict(cf),
        "host_unbound_symbols_top": dict(host_syms.most_common(15)),
        "manifest": manifest,
        "host": host.as_manifest(),
        "funnel": {k: dict(v) for k, v in funnel.items()},
        "drops": dict(drops),
        "rates": {
            "closure_failure": round(tot["closure_fail"] / closable, 3) if closable else 0.0,
            "closure_failure_context": round(cf["context"] / closable, 3) if closable else 0.0,
            "closure_failure_host_typecheck": round(cf["host"] / closable, 3) if closable else 0.0,
            "closure_failure_budget": round(cf["budget"] / closable, 3) if closable else 0.0,
            "apply_ok_given_closed": round(tot["apply_ok"] / tot["closure_ok"], 3) if tot["closure_ok"] else 0.0,
            "keep_share_of_labeled": round(keep_n / (keep_n + tot["ROLLBACK"]), 3) if keep_n + tot["ROLLBACK"] else 0.0,
            "keep_tested_share": round(keep_tested / keep_n, 3) if keep_n else 0.0,
            "units_to_train": round(len(train) / tot["units"], 3) if tot["units"] else 0.0,
            "intent_llm_share": round(sum(1 for r in rows if r["meta"].get("intent_source") == "llm") / len(rows), 3) if rows else 0.0,
        },
        "labels": dict(Counter(r["verify"]["label"] for r in rows)),
        "rollback_reasons": dict(Counter(r["verify"]["reason"] for r in neg)),
        "keep_test_status": dict(Counter(r["verify"]["test"]["status"] for r in keep)),
        "train_labels": dict(Counter(r["verify"]["label"] for r in train)),
        "split_cross_groups": len(train_groups & eval_groups),
        "train": scan_rows(train),
        "eval": scan_rows(ev),
        "all": scan_rows(rows),
        "timing_sec": round(time.time() - started, 1),
    }
    R["gates"] = evaluate_gates(R)
    R["export_allowed"] = gates_pass(R["gates"])
    manifest["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    manifest["files"] = {
        p.name: {"rows": sum(1 for _ in p.open(encoding="utf-8")), "sha256": sha256_file(p)}
        for p in sorted(out.glob("*.jsonl"))
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (out / "report.json").write_text(json.dumps(R, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_markdown(R, out / "report.md")
    if not opts.get("keep_trees"):
        import shutil

        shutil.rmtree(out / ".trees", ignore_errors=True)
    log(f"done in {R['timing_sec']}s: train={len(train)} eval={len(ev)} neg={len(train_neg)}+{len(eval_neg)} export_allowed={R['export_allowed']}")
    return R


def export(out: Path, force: bool = False) -> int:
    R = json.loads((out / "report.json").read_text(encoding="utf-8"))
    if not R.get("export_allowed") and not force:
        failed = [g["gate"] for g in R["gates"] if g["level"] == "block" and not g["ok"]]
        log(f"export refused: blocking gates failed: {failed}")
        return 3
    import export_sft

    rc = export_sft.main(
        [str(out / "train.jsonl"), "--profile", "dialect", "--out", str(out / "sft.jsonl"), "--manifest", str(out / "sft-manifest.json")]
    )
    mpath = out / "sft-manifest.json"
    if mpath.is_file():
        m = json.loads(mpath.read_text(encoding="utf-8"))
        run_m = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
        # export_sft looks for ../aura-grok; record the pinned host of this run instead.
        m["host"] = run_m["host"]["aura_sha"]
        m["host_bin_sha256"] = run_m["host"]["bin_sha256"]
        m["pipeline_run"] = run_m["command"]
        m["sft_sha256"] = sha256_file(out / "sft.jsonl")
        mpath.write_text(json.dumps(m, indent=2) + "\n", encoding="utf-8")
    return rc
