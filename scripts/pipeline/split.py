"""Stage 6: exact/near dedup, per-commit and per-pattern caps, time holdout."""

from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict

from edsl_patch import normalize_source

NEAR_DUP_J = 0.9
CAP_PER_COMMIT = 8
CAP_PER_NAME = 4
CAP_PER_SHAPE = 3
EVAL_SHARE = 0.15


def prompt_text(row: dict) -> str:
    inp = row.get("input") or {}
    return normalize_source(inp.get("source") or "") + "\nintent: " + str(inp.get("intent") or "")


def completion_text(row: dict) -> str:
    return json.dumps(row.get("target") or [], sort_keys=True)


def shingles(text: str, n: int = 5) -> set[str]:
    t = " ".join(text.split())
    return {t[i : i + n] for i in range(max(1, len(t) - n + 1))}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def diff_shape(row: dict) -> str:
    """Coarse change pattern: name-agnostic token delta of old -> new body."""
    meta = row.get("meta") or {}
    old = meta.get("old_body") or ""
    new = (row.get("target") or [{}])[-1].get("body") or ""
    name = meta.get("name") or ""
    tok = lambda s: Counter(t for t in re.findall(r"[^\s()]+", s) if t != name)  # noqa: E731
    a, b = tok(old), tok(new)
    plus = sorted((b - a).elements())
    minus = sorted((a - b).elements())
    return json.dumps([plus[:12], minus[:12]])


def dedup(rows: list[dict], drops: Counter) -> list[dict]:
    """rows sorted oldest first; later duplicates are dropped."""
    out: list[dict] = []
    seen_exact: set[tuple[str, str]] = set()
    by_prompt: dict[str, set[str]] = defaultdict(set)
    for r in rows:
        by_prompt[prompt_text(r)].add(completion_text(r))
    conflicted = {p for p, cs in by_prompt.items() if len(cs) > 1}
    sh: list[set[str]] = []
    for r in rows:
        p, c = prompt_text(r), completion_text(r)
        if (p, c) in seen_exact:
            drops["exact-dup"] += 1
            continue
        if p in conflicted:
            drops["conflict"] += 1
            continue
        s = shingles(p + "\n" + c)
        if any(jaccard(s, o) >= NEAR_DUP_J for o in sh):
            drops["near-dup"] += 1
            continue
        seen_exact.add((p, c))
        sh.append(s)
        out.append(r)
    return out


def cap(rows: list[dict], drops: Counter) -> list[dict]:
    per_commit: Counter = Counter()
    per_name: Counter = Counter()
    per_shape: Counter = Counter()
    out = []
    for r in rows:
        m = r.get("meta") or {}
        ck = m.get("commit_group")
        nk = (m.get("repo"), m.get("file"), m.get("name"), m.get("label"))
        sk = (m.get("repo"), diff_shape(r))
        if per_commit[ck] >= CAP_PER_COMMIT:
            drops["cap-commit"] += 1
            continue
        if per_name[nk] >= CAP_PER_NAME:
            drops["cap-name"] += 1
            continue
        if per_shape[sk] >= CAP_PER_SHAPE:
            drops["cap-shape"] += 1
            continue
        per_commit[ck] += 1
        per_name[nk] += 1
        per_shape[sk] += 1
        out.append(r)
    return out


def holdout(rows: list[dict], share: float = EVAL_SHARE) -> dict[str, str]:
    """commit_group -> train|eval. The latest `share` of commits per repo go to eval."""
    groups: dict[str, dict[str, int]] = defaultdict(dict)
    for r in rows:
        m = r["meta"]
        groups[m["repo"]][m["commit_group"]] = int(m.get("commit_time") or 0)
    split: dict[str, str] = {}
    for repo, g in groups.items():
        ordered = sorted(g, key=lambda k: (g[k], k))
        n_eval = max(1, math.ceil(len(ordered) * share)) if len(ordered) >= 3 else 0
        for i, k in enumerate(ordered):
            split[k] = "eval" if i >= len(ordered) - n_eval else "train"
    return split


def leak_filter(train: list[dict], eval_rows: list[dict], drops: Counter) -> list[dict]:
    """Drop eval rows that are near-duplicates of a train row."""
    tsh = [shingles(prompt_text(r) + "\n" + completion_text(r)) for r in train]
    out = []
    for r in eval_rows:
        s = shingles(prompt_text(r) + "\n" + completion_text(r))
        if any(jaccard(s, o) >= NEAR_DUP_J for o in tsh):
            drops["eval-leak"] += 1
            continue
        out.append(r)
    return out
