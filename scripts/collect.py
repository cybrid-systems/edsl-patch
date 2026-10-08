#!/usr/bin/env python3
"""Continuously harvest EDSL patches from real sibling Aura business code.

Sources (repeatable, cursor-based):
  git     consecutive commits that changed a named define in *.aura
  live    current module files (Unify KV plant by default)
  journal Unify evolve journal generations (cursor only; bodies come from git)

Apply-verify each candidate. Append to data/raw/business.jsonl.
Re-running skips SHAs already in the cursor file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PARENT = ROOT.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from apply import apply_patch, apply_succeeded, pick_bin, pick_lib
from edsl_patch import PatchError, validate_patch
from farm_budget import resolve
from parse_aura import (
    bodies_equivalent,
    code_symbols,
    extract_defines,
    focused_source,
    lambda_params,
    paren_balanced,
    patch_for,
)

DEFAULT_REPOS = (
    "unify",
    "aether",
    "daedalus",
    "hephaestus",
    "prometheus",
    "hermes",
    "flux",
)
DEFAULT_GLOBS = (
    "unify/projects/kv/lib/*.aura",
    "unify/lib/*.aura",
    "aether/lib/*.aura",
    "daedalus/lib/*.aura",
    "hephaestus/lib/*.aura",
    "prometheus/lib/*.aura",
    "hermes/lib/*.aura",
    "flux/lib/*.aura",
)
CURSOR_PATH = ROOT / "data" / "raw" / "collect-cursor.json"
OUT_PATH = ROOT / "data" / "raw" / "business.jsonl"


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True)


def git_ok(repo: Path) -> bool:
    return (repo / ".git").exists() or (repo / ".git").is_file()


def load_cursor(path: Path) -> dict:
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"git": {}, "seen": []}


def save_cursor(path: Path, cur: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cur, indent=2) + "\n", encoding="utf-8")


def sample_id(repo: str, rel: str, name: str, parent: str, child: str) -> str:
    key = f"{repo}:{rel}:{name}:{parent[:8]}:{child[:8]}"
    return "biz-" + hashlib.sha1(key.encode()).hexdigest()[:12]


_SUBJECT_PREFIX = re.compile(r"^(?:[A-Za-z][\w-]*)(?:\([^)\n]{0,40}\))?!?:\s+")
_SHA_SUFFIX = re.compile(r"@[0-9a-fA-F]{7,}$")
_HOST_REV: str | None = None


def host_bin_sha() -> str:
    blob = hashlib.sha256()
    blob.update(pick_bin().read_bytes())
    return blob.hexdigest()


def host_rev() -> str:
    global _HOST_REV
    if _HOST_REV is None:
        repo = PARENT / "aura-grok"
        try:
            _HOST_REV = git(repo, "rev-parse", "HEAD").strip()
        except (subprocess.CalledProcessError, OSError):
            _HOST_REV = ""
    return _HOST_REV


def commit_message(repo: Path, sha: str) -> tuple[str, str]:
    try:
        text = git(repo, "log", "-1", "--format=%s%x00%b", sha)
    except (subprocess.CalledProcessError, OSError, UnicodeDecodeError):
        return "", ""
    if "\x00" in text:
        subject, body = text.split("\x00", 1)
    else:
        subject, body = text, ""
    return " ".join(subject.split()), body.strip()


def semantic_summary(subject: str) -> str:
    """Short phrase from a commit subject. Never `name@sha`."""
    raw = " ".join((subject or "").split())
    text = _SUBJECT_PREFIX.sub("", raw).strip() or raw
    text = _SHA_SUFFIX.sub("", text).strip()
    if len(text) > 72:
        cut = text[:72]
        text = cut.rsplit(" ", 1)[0] if " " in cut else cut
    return text.strip(" .:-")


def make_intent(name: str, subject: str, body: str) -> str:
    subject = " ".join((subject or "").split())
    if not subject:
        return ""
    extra = _commit_detail(body, subject)
    text = f"Rebind {name}: {subject}"
    if extra:
        text += ". " + extra
    return text


def _commit_detail(body: str, subject: str) -> str:
    lines: list[str] = []
    for line in (body or "").splitlines():
        stripped = line.strip()
        if not stripped:
            if lines:
                break
            continue
        low = stripped.lower()
        if low.startswith(("signed-off-by:", "co-authored-by:", "change-id:")):
            continue
        lines.append(stripped)
    para = " ".join(lines)
    if not para or para == subject:
        return ""
    if para.startswith(subject):
        para = para[len(subject) :].lstrip(" .:-")
    if len(para) > 240:
        cut = para[:240]
        para = cut.rsplit(" ", 1)[0] if " " in cut else cut
    return para.strip()


def _has_abs_path(text: str) -> bool:
    return "/workspace/" in text or "/home/" in text


def noise_reason(name: str, rel: str, body: str) -> str | None:
    lname = name.lower()
    lfile = rel.replace("\\", "/")
    if "stamp-info" in lname or "stamp-system" in lname or "self_evolve_stamp" in lfile:
        return "stamp"
    if "traj_id" in body:
        return "stamp"
    return None


def child_only_helpers(parent_src: str, child_src: str, body: str, name: str) -> set[str]:
    """Defines that exist only on the child commit and are called by the new body."""
    added = set(extract_defines(child_src)) - set(extract_defines(parent_src))
    if not added:
        return set()
    refs = code_symbols(body) - lambda_params(body) - {name}
    return refs & added


def reject_change(
    name: str,
    rel: str,
    parent_src: str,
    child_src: str,
    old_body: str,
    new_body: str,
) -> str | None:
    if noise_reason(name, rel, new_body):
        return "stamp"
    if not paren_balanced(new_body):
        return "unbalanced"
    if bodies_equivalent(old_body, new_body):
        return "comment-only"
    if child_only_helpers(parent_src, child_src, new_body, name):
        return "child-helper"
    return None


def shape_git_change(
    *,
    repo_name: str,
    repo: Path,
    file: str,
    name: str,
    parent: str,
    child: str,
    old: str,
    new: str,
    new_body: str,
    old_body: str | None = None,
) -> tuple[dict | None, str]:
    if old_body is None:
        old_body = extract_defines(old).get(name, "")
    reason = reject_change(name, file, old, new, old_body, new_body)
    if reason:
        return None, reason
    subject, detail = commit_message(repo, child)
    intent = make_intent(name, subject, detail)
    summary = semantic_summary(subject)
    if not intent or not summary:
        return None, "no-intent"
    focus = focused_source(old, name)
    if not focus:
        return None, "focus"
    if _has_abs_path(focus) or _has_abs_path(new_body):
        return None, "abs-path"
    return (
        {
            "id": sample_id(repo_name, file, name, parent, child),
            "repo": repo_name,
            "file": file,
            "name": name,
            "parent": parent,
            "child": child,
            "source": focus,
            "body": new_body,
            "summary": summary,
            "intent": intent,
        },
        "keep",
    )


def file_commits(repo: Path, rel: str) -> list[str]:
    out = git(repo, "log", "--pretty=%H", "--", rel)
    hashes = [h for h in out.split() if h]
    hashes.reverse()  # oldest first
    return hashes


def git_show(repo: Path, sha: str, rel: str) -> str | None:
    try:
        return git(repo, "show", f"{sha}:{rel}")
    except (subprocess.CalledProcessError, UnicodeDecodeError, OSError):
        return None


def iter_repo_aura(parent: Path, repo_name: str, glob: str) -> list[Path]:
    return sorted(parent.glob(glob))


def harvest_git(
    *,
    parent: Path,
    globs: list[str],
    cursor: dict,
    limit: int | None,
    drops: dict[str, int] | None = None,
) -> list[dict]:
    rows = []
    git_cur = cursor.setdefault("git", {})
    for pattern in globs:
        for path in parent.glob(pattern):
            if not path.is_file():
                continue
            try:
                rel = str(path.relative_to(parent))
            except ValueError:
                continue
            repo_name = rel.split("/", 1)[0]
            repo = parent / repo_name
            if not git_ok(repo):
                continue
            inner = str(path.relative_to(repo))
            key = f"{repo_name}:{inner}"
            shas = file_commits(repo, inner)
            if not shas:
                continue
            for parent_sha, child_sha in zip(shas, shas[1:]):
                old = git_show(repo, parent_sha, inner)
                new = git_show(repo, child_sha, inner)
                if not old or not new or len(old) > 80_000:
                    git_cur[key] = child_sha
                    continue
                old_defs = extract_defines(old)
                new_defs = extract_defines(new)
                for name, new_body in new_defs.items():
                    if name not in old_defs:
                        continue
                    if old_defs[name] == new_body:
                        continue
                    cand, why = shape_git_change(
                        repo_name=repo_name,
                        repo=repo,
                        file=inner,
                        name=name,
                        parent=parent_sha,
                        child=child_sha,
                        old=old,
                        new=new,
                        old_body=old_defs[name],
                        new_body=new_body,
                    )
                    if cand is None:
                        if drops is not None:
                            drops[why] = drops.get(why, 0) + 1
                        continue
                    rows.append(cand)
                    if limit is not None and len(rows) >= limit:
                        git_cur[key] = child_sha
                        return rows
                git_cur[key] = child_sha
    return rows


def harvest_live(paths: list[Path], *, identity: bool) -> list[dict]:
    if not identity:
        return []
    rows = []
    for path in paths:
        src = path.read_text(encoding="utf-8")
        defs = extract_defines(src)
        for name, body in defs.items():
            if noise_reason(name, path.name, body):
                continue
            focus = focused_source(src, name)
            if not focus:
                continue
            rows.append(
                {
                    "id": sample_id("live", str(path), name, "HEAD", "HEAD"),
                    "repo": path.parts[-4] if len(path.parts) >= 4 else "live",
                    "file": path.name,
                    "name": name,
                    "parent": "HEAD",
                    "child": "HEAD",
                    "source": focus,
                    "body": body,
                    "summary": semantic_summary(f"keep {name}") or f"keep {name}",
                    "intent": f"Keep the current body of {name}.",
                }
            )
    return rows


def to_sample(cand: dict) -> dict:
    target = patch_for(cand["name"], cand["body"], cand["summary"])
    validate_patch(target)
    inp: dict = {"source": cand["source"]}
    if cand.get("intent"):
        inp["intent"] = cand["intent"]
    return {
        "id": cand["id"],
        "input": inp,
        "target": target,
        "meta": {
            "repo": cand.get("repo"),
            "file": cand.get("file"),
            "name": cand["name"],
            "parent": cand.get("parent"),
            "child": cand.get("child"),
            "focus": "define+def-use",
            "host": host_rev(),
        },
        "verify": {"apply_ok": True},
        "_extra_path": cand.get("extra_path"),
    }


def doctor(*, parent: Path = PARENT, globs: list[str] | None = None, cursor: Path = CURSOR_PATH) -> int:
    """Print layout diagnosis. Never writes jsonl. Always exit 0."""
    globs = globs or list(DEFAULT_GLOBS)
    try:
        bin_path = pick_bin()
        print(f"doctor: aura-bin found {bin_path}")
    except SystemExit:
        print("doctor: aura-bin missing")
    try:
        lib = pick_lib()
        print(f"doctor: aura-lib found {lib}")
    except SystemExit:
        print("doctor: aura-lib missing")
    for pattern in globs:
        n = len(list(parent.glob(pattern)))
        print(f"doctor: glob {pattern} matches={n}")
    for name in DEFAULT_REPOS:
        repo = parent / name
        print(f"doctor: sibling {name} git={'yes' if git_ok(repo) else 'no'}")
    seen = 0
    if cursor.is_file():
        try:
            seen = len(load_cursor(cursor).get("seen") or [])
        except json.JSONDecodeError:
            seen = 0
    print(f"doctor: cursor {cursor} seen={seen}")
    return 0


def verify_candidates(
    cands: list[dict],
    *,
    timeout: int,
    out: Path | None = None,
    seen: set[str] | None = None,
) -> tuple[list[dict], dict[str, int]]:
    kept = []
    n = len(cands)
    seen = seen if seen is not None else set()
    counters = {"skip-seen": 0, "skip-illegal": 0, "skip-apply": 0, "keep": 0}
    for i, cand in enumerate(cands, 1):
        label = f"{cand.get('repo')}:{cand.get('name')}"
        if cand.get("id") in seen:
            counters["skip-seen"] += 1
            print(f"collect: {i}/{n} skip-seen {label}", flush=True)
            continue
        try:
            sample = to_sample(cand)
        except PatchError:
            counters["skip-illegal"] += 1
            print(f"collect: {i}/{n} skip-illegal {label}", flush=True)
            continue
        extra = sample.pop("_extra_path", None)
        try:
            result = apply_patch(
                sample["input"]["source"],
                sample["target"],
                timeout=timeout,
                extra_path=extra,
            )
        except (PatchError, subprocess.TimeoutExpired, OSError) as e:
            counters["skip-apply"] += 1
            print(f"collect: {i}/{n} skip-apply {label} {e}", flush=True)
            continue
        if not apply_succeeded(result):
            counters["skip-apply"] += 1
            print(f"collect: {i}/{n} skip-apply {label}", flush=True)
            continue
        sample["verify"] = {
            "apply_ok": True,
            "expected_source": result.get("source") or "",
        }
        kept.append(sample)
        counters["keep"] += 1
        if out is not None:
            append_jsonl(out, [sample], seen)
        print(f"collect: {i}/{n} keep {label}", flush=True)
    return kept, counters


def _prompt_key(cand: dict) -> tuple[str, str]:
    src = " ".join((cand.get("source") or "").split())
    return src, cand.get("intent") or ""


def drop_ambiguous(cands: list[dict], drops: Counter) -> list[dict]:
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for cand in cands:
        groups[_prompt_key(cand)].append(cand)
    kept: list[dict] = []
    for items in groups.values():
        bodies = {it.get("body") for it in items}
        if len(bodies) > 1:
            drops["ambiguous"] += len(items)
            continue
        if len(items) > 1:
            drops["duplicate"] += len(items) - 1
        kept.append(items[0])
    return kept


def rewrite_business(path: Path, *, dry_run: bool, timeout: int, cursor_path: Path) -> int:
    """Reshape an existing business jsonl from parent/child git objects.

    Replaces whole-file prompts with a closed define excerpt, commit intent,
    and a semantic summary. Does not append new commits.
    """
    if not path.is_file():
        print(f"collect: rewrite missing {path}", file=sys.stderr)
        return 1
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    drops: Counter = Counter()
    shaped: list[dict] = []
    for obj in rows:
        meta = obj.get("meta") or {}
        repo_name = meta.get("repo")
        rel = meta.get("file")
        name = meta.get("name")
        parent_sha = meta.get("parent")
        child_sha = meta.get("child")
        if not all(isinstance(x, str) and x for x in (repo_name, rel, name, parent_sha, child_sha)):
            drops["bad-meta"] += 1
            continue
        repo = PARENT / repo_name
        if not git_ok(repo):
            drops["missing-repo"] += 1
            continue
        old = git_show(repo, parent_sha, rel)
        new = git_show(repo, child_sha, rel)
        if not old or not new:
            drops["missing-git"] += 1
            continue
        old_defs = extract_defines(old)
        new_defs = extract_defines(new)
        if name not in old_defs or name not in new_defs:
            drops["missing-define"] += 1
            continue
        cand, why = shape_git_change(
            repo_name=repo_name,
            repo=repo,
            file=rel,
            name=name,
            parent=parent_sha,
            child=child_sha,
            old=old,
            new=new,
            old_body=old_defs[name],
            new_body=new_defs[name],
        )
        if cand is None:
            drops[why] += 1
            continue
        shaped.append(cand)
    shaped = drop_ambiguous(shaped, drops)
    print(
        "collect: rewrite shaped "
        + " ".join(f"{k}={v}" for k, v in sorted(drops.items()))
        + f" keep={len(shaped)} of {len(rows)}"
    )
    if dry_run:
        return 0
    samples, counters = verify_candidates(shaped, timeout=timeout, out=None, seen=set())
    print(
        "collect: rewrite apply "
        + " ".join(f"{k}={v}" for k, v in sorted(counters.items()))
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for sample in samples:
            f.write(json.dumps(sample, ensure_ascii=False) + "\n")
    tmp.replace(path)
    if cursor_path.is_file():
        cursor = load_cursor(cursor_path)
    else:
        cursor = {"git": {}, "seen": []}
    cursor["shape"] = "focus-v1"
    seen = set(cursor.get("seen") or [])
    for obj in rows:
        if obj.get("id"):
            seen.add(obj["id"])
    for sample in samples:
        seen.add(sample["id"])
    cursor["seen"] = sorted(seen)
    save_cursor(cursor_path, cursor)
    print(f"collect: rewrite wrote {len(samples)} -> {path}")
    return 0 if samples else 1


def append_jsonl(path: Path, rows: list[dict], seen: set[str]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with path.open("a", encoding="utf-8") as f:
        for row in rows:
            if row["id"] in seen:
                continue
            seen.add(row["id"])
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            n += 1
    return n


def _reject_reason(detail: object) -> str:
    if isinstance(detail, list) and detail:
        text = " ".join(str(part) for part in detail)
        if "unbound variable" in text and "arity" in text:
            return "unbound+arity"
        if "unbound variable" in text:
            return "unbound"
        if "typecheck" in text:
            return "typecheck"
        head = str(detail[0])
        return head if head else "mutation-failed"
    if detail in (None, False):
        return "rejected"
    return "rejected"


def reverify_business(path: Path, *, timeout: int, cursor_path: Path) -> int:
    """Re-apply each business row. Keep only a real #t rebind and rewrite expected_source."""
    if not path.is_file():
        print(f"collect: reverify missing {path}", file=sys.stderr)
        return 1
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    host = host_rev()
    host_bin = host_bin_sha()
    kept: list[dict] = []
    reasons: Counter = Counter()
    n = len(rows)
    for i, row in enumerate(rows, 1):
        label = f"{(row.get('meta') or {}).get('repo')}:{(row.get('meta') or {}).get('name')}"
        try:
            result = apply_patch(
                row["input"]["source"],
                row["target"],
                timeout=timeout,
            )
        except (PatchError, subprocess.TimeoutExpired, OSError) as e:
            reasons["apply-error"] += 1
            print(f"collect: {i}/{n} drop-apply {label} {e}", flush=True)
            continue
        if not apply_succeeded(result):
            reason = _reject_reason((result.get("synthesis") or {}).get("detail"))
            reasons[reason] += 1
            print(f"collect: {i}/{n} drop-{reason} {label}", flush=True)
            continue
        verify = dict(row.get("verify") or {})
        verify["apply_ok"] = True
        verify["expected_source"] = result.get("source") or ""
        row["verify"] = verify
        meta = dict(row.get("meta") or {})
        meta["host"] = host
        meta["host_bin"] = host_bin
        row["meta"] = meta
        kept.append(row)
        print(f"collect: {i}/{n} keep {label}", flush=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for row in kept:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    tmp.replace(path)
    if cursor_path.is_file():
        cursor = load_cursor(cursor_path)
    else:
        cursor = {"git": {}, "seen": []}
    cursor["shape"] = "reverify-v1"
    seen = set(cursor.get("seen") or [])
    for row in rows:
        if row.get("id"):
            seen.add(row["id"])
    cursor["seen"] = sorted(seen)
    save_cursor(cursor_path, cursor)
    print(
        "collect: reverify "
        + " ".join(f"{k}={v}" for k, v in sorted(reasons.items()))
        + f" keep={len(kept)} of {n} host={host} -> {path}"
    )
    return 0 if kept else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", type=Path, default=OUT_PATH)
    p.add_argument("--cursor", type=Path, default=CURSOR_PATH)
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help="max git candidates before apply (default: budget collect_limit, smoke=5)",
    )
    p.add_argument("--timeout", type=int, default=15)
    p.add_argument("--identity", action="store_true", help="also emit identity rebinds of live files")
    p.add_argument("--doctor", action="store_true", help="print sibling/aura diagnosis; no jsonl")
    p.add_argument(
        "--rewrite",
        action="store_true",
        help="reshape the existing business jsonl (focused context, commit intent)",
    )
    p.add_argument(
        "--reverify",
        action="store_true",
        help="re-apply business.jsonl and drop rows whose rebind is not #t",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="with --rewrite, classify only; do not apply or write",
    )
    p.add_argument(
        "--glob",
        action="append",
        dest="globs",
        help="repeatable glob under grok-dev parent (default: span libs + kv)",
    )
    args = p.parse_args(argv)

    if args.doctor:
        return doctor(globs=args.globs)

    if args.rewrite:
        return rewrite_business(
            args.out, dry_run=args.dry_run, timeout=args.timeout, cursor_path=args.cursor
        )

    if args.reverify:
        return reverify_business(args.out, timeout=args.timeout, cursor_path=args.cursor)

    cursor = load_cursor(args.cursor)
    seen = set(cursor.get("seen") or [])
    if args.out.is_file():
        for line in args.out.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                seen.add(json.loads(line)["id"])
            except (json.JSONDecodeError, KeyError):
                continue
    globs = args.globs or list(DEFAULT_GLOBS)
    if args.limit is None:
        limit = int(resolve()["collect_limit"])
    else:
        limit = args.limit if args.limit > 0 else None

    drops: dict[str, int] = {}
    cands = harvest_git(parent=PARENT, globs=globs, cursor=cursor, limit=limit, drops=drops)
    if drops:
        print("collect: drops " + " ".join(f"{k}={v}" for k, v in sorted(drops.items())))
    live_paths = []
    for g in globs:
        live_paths.extend(PARENT.glob(g))
    cands.extend(harvest_live(live_paths, identity=args.identity))

    before = len(seen)
    kept, counters = verify_candidates(
        cands, timeout=args.timeout, out=args.out, seen=seen
    )
    added = len(seen) - before
    cursor["seen"] = sorted(seen)
    save_cursor(args.cursor, cursor)
    print(
        f"collect: candidates={len(cands)} verified={len(kept)} "
        f"appended={added} total_seen={len(seen)} "
        f"skip-seen={counters['skip-seen']} skip-illegal={counters['skip-illegal']} "
        f"skip-apply={counters['skip-apply']} keep={counters['keep']} -> {args.out}"
    )
    return 0 if kept or added or seen else 1


if __name__ == "__main__":
    raise SystemExit(main())
