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
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PARENT = ROOT.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from apply import apply_patch, pick_bin, pick_lib
from edsl_patch import PatchError, validate_patch
from farm_budget import resolve
from parse_aura import extract_defines, patch_for

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


def file_commits(repo: Path, rel: str) -> list[str]:
    out = git(repo, "log", "--pretty=%H", "--", rel)
    hashes = [h for h in out.split() if h]
    hashes.reverse()  # oldest first
    return hashes


def git_show(repo: Path, sha: str, rel: str) -> str | None:
    try:
        return git(repo, "show", f"{sha}:{rel}")
    except subprocess.CalledProcessError:
        return None


def iter_repo_aura(parent: Path, repo_name: str, glob: str) -> list[Path]:
    return sorted(parent.glob(glob))


def harvest_git(
    *,
    parent: Path,
    globs: list[str],
    cursor: dict,
    limit: int | None,
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
                extra = str(path.parent)
                for name, new_body in new_defs.items():
                    if name not in old_defs:
                        continue
                    if old_defs[name] == new_body:
                        continue
                    rows.append(
                        {
                            "id": sample_id(repo_name, inner, name, parent_sha, child_sha),
                            "repo": repo_name,
                            "file": inner,
                            "name": name,
                            "parent": parent_sha,
                            "child": child_sha,
                            "source": old,
                            "body": new_body,
                            "summary": f"{name}@{child_sha[:8]}",
                            "extra_path": extra,
                        }
                    )
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
        extra = str(path.parent)
        for name, body in defs.items():
            rows.append(
                {
                    "id": sample_id("live", str(path), name, "HEAD", "HEAD"),
                    "repo": path.parts[-4] if len(path.parts) >= 4 else "live",
                    "file": path.name,
                    "name": name,
                    "parent": "HEAD",
                    "child": "HEAD",
                    "source": src,
                    "body": body,
                    "summary": f"identity-{name}",
                    "extra_path": extra,
                }
            )
    return rows


def to_sample(cand: dict) -> dict:
    target = patch_for(cand["name"], cand["body"], cand["summary"])
    validate_patch(target)
    return {
        "id": cand["id"],
        "input": {"source": cand["source"]},
        "target": target,
        "meta": {
            "repo": cand.get("repo"),
            "file": cand.get("file"),
            "name": cand["name"],
            "parent": cand.get("parent"),
            "child": cand.get("child"),
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
        if not result.get("ok"):
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
        "--glob",
        action="append",
        dest="globs",
        help="repeatable glob under grok-dev parent (default: span libs + kv)",
    )
    args = p.parse_args(argv)

    if args.doctor:
        return doctor(globs=args.globs)

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

    cands = harvest_git(parent=PARENT, globs=globs, cursor=cursor, limit=limit)
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
