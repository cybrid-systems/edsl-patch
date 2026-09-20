#!/usr/bin/env python3
"""Quality + diversity filter for farm shards. No Aura host required."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from edsl_patch import PatchError, normalize_source, validate_patch
from parse_aura import extract_defines

BANNED = ("eval", "synthesize:define", "fiber:spawn", "<think>", "node-id", "#nid")
SHAPE_MIN = 200
SHAPE_FRAC = 0.40


def shape_class(body: str) -> str:
    b = body or ""
    ns = normalize_source(b)
    m = re.fullmatch(r"\(lambda \(([A-Za-z][A-Za-z0-9:!?_-]*)\) \1\)", ns)
    if m:
        return "id"
    if "(if " in b:
        return "if"
    if any(tok in b for tok in ("null?", "(car ", "(cdr ", "(cons ")):
        return "list"
    if any(tok in b for tok in ("(+ ", "(- ", "(* ", "(/ ", "(< ")):
        return "arith"
    if re.search(r"\([A-Za-z][A-Za-z0-9:!?_-]*\s+", b):
        return "call-helper"
    return "other"


def sample_key(source: str, name: str, body: str) -> str:
    raw = f"{normalize_source(source)}\0{name}\0{normalize_source(body)}"
    return hashlib.sha1(raw.encode()).hexdigest()


def banned(text: str) -> str | None:
    """Flag real call tokens, not eval-current, daed:node-id, or comments."""
    t = text or ""
    if re.search(r"\(eval(?!-current)\b", t):
        return "eval"
    if "synthesize:define" in t:
        return "synthesize:define"
    if re.search(r"\(fiber:spawn\b", t):
        return "fiber:spawn"
    if "<think>" in t:
        return "<think>"
    if re.search(r"(?<![:\w])node-id\b", t) or re.search(r"(?<![:\w])#nid\b", t):
        return "node-id"
    return None


def name_in_source(source: str, name: str) -> bool:
    if not name:
        return False
    defs = extract_defines(source)
    if name in defs:
        return True
    if name.startswith("*") and name in (source or ""):
        return True
    return bool(re.search(rf"\(define\s+(\({re.escape(name)}\b|{re.escape(name)}\b)", source or ""))


def inspect(sample: dict) -> tuple[str, str, str, str]:
    source = (sample.get("input") or {}).get("source") or ""
    target = sample.get("target") or []
    name = ""
    body = ""
    summary = ""
    for step in target:
        if step.get("kind") in ("synthesis", "refuse"):
            name = step.get("name") or ""
            body = step.get("body") or ""
            summary = step.get("summary") or step.get("why") or ""
    return source, name, body, summary


def filter_reason(
    sample: dict,
    *,
    project: str,
    cap_per_summary: int,
    summary_counts: dict[tuple[str, str], int],
    seen: set[str],
    shape_counts: dict[str, int],
    kept: int,
    enforce_shape: bool,
) -> str | None:
    source, name, body, summary = inspect(sample)
    try:
        validate_patch(sample.get("target"))
    except (PatchError, TypeError, KeyError):
        return "schema"
    defs = extract_defines(source)
    if name and defs.get(name) is not None:
        if normalize_source(defs[name]) == normalize_source(body):
            return "noop"
    key = sample_key(source, name, body)
    if key in seen:
        return "dedup"
    sc = summary_counts.get((project, summary), 0)
    if cap_per_summary and sc >= cap_per_summary:
        return "summary-cap"
    cls = shape_class(body)
    if enforce_shape and kept >= SHAPE_MIN:
        if (shape_counts.get(cls, 0) + 1) > SHAPE_FRAC * max(kept, 1):
            return "shape-cap"
    hit = banned(source) or banned(body)
    if hit:
        return "token"
    if not name_in_source(source, name):
        return "name-in-plant"
    return None


def accept(
    sample: dict,
    *,
    project: str,
    cap_per_summary: int,
    summary_counts: dict,
    seen: set[str],
    shape_counts: dict,
    kept: int,
    enforce_shape: bool,
) -> bool:
    why = filter_reason(
        sample,
        project=project,
        cap_per_summary=cap_per_summary,
        summary_counts=summary_counts,
        seen=seen,
        shape_counts=shape_counts,
        kept=kept,
        enforce_shape=enforce_shape,
    )
    if why:
        return False
    source, name, body, summary = inspect(sample)
    seen.add(sample_key(source, name, body))
    summary_counts[(project, summary)] = summary_counts.get((project, summary), 0) + 1
    cls = shape_class(body)
    shape_counts[cls] = shape_counts.get(cls, 0) + 1
    return True


def read_jsonl(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def run_filter(rows: list[dict], *, project: str, cap: int, enforce_shape: bool) -> tuple[list[dict], dict[str, int]]:
    drops = {
        "schema": 0,
        "noop": 0,
        "dedup": 0,
        "summary-cap": 0,
        "shape-cap": 0,
        "token": 0,
        "name-in-plant": 0,
    }
    kept_rows = []
    seen: set[str] = set()
    summary_counts: dict[tuple[str, str], int] = {}
    shape_counts: dict[str, int] = {}
    for sample in rows:
        why = filter_reason(
            sample,
            project=project,
            cap_per_summary=cap,
            summary_counts=summary_counts,
            seen=seen,
            shape_counts=shape_counts,
            kept=len(kept_rows),
            enforce_shape=enforce_shape,
        )
        if why:
            drops[why] = drops.get(why, 0) + 1
            continue
        source, name, body, summary = inspect(sample)
        seen.add(sample_key(source, name, body))
        summary_counts[(project, summary)] = summary_counts.get((project, summary), 0) + 1
        cls = shape_class(body)
        shape_counts[cls] = shape_counts.get(cls, 0) + 1
        kept_rows.append(sample)
    return kept_rows, drops


def check_hard(rows: list[dict], *, strict_caps: bool, project: str, cap: int) -> int:
    """Exit 1 if schema/token/name-in-plant fail. Caps warn unless strict."""
    bad = 0
    warn = 0
    seen: set[str] = set()
    summary_counts: dict[tuple[str, str], int] = {}
    shape_counts: dict[str, int] = {}
    kept = 0
    for sample in rows:
        why = filter_reason(
            sample,
            project=project,
            cap_per_summary=cap,
            summary_counts=summary_counts,
            seen=seen,
            shape_counts=shape_counts,
            kept=kept,
            enforce_shape=True,
        )
        if why in ("schema", "token", "name-in-plant"):
            print(f"quality: fail {why} id={sample.get('id')}", file=sys.stderr)
            bad += 1
            continue
        if why in ("summary-cap", "shape-cap"):
            print(f"quality: warn {why} id={sample.get('id')}", file=sys.stderr)
            warn += 1
            if strict_caps:
                bad += 1
            continue
        if why:
            continue
        source, name, body, summary = inspect(sample)
        seen.add(sample_key(source, name, body))
        summary_counts[(project, summary)] = summary_counts.get((project, summary), 0) + 1
        shape_counts[shape_class(body)] = shape_counts.get(shape_class(body), 0) + 1
        kept += 1
    print(f"quality: check kept={kept} hard-fail={bad} cap-warn={warn}")
    return 1 if bad else 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--check", type=Path)
    p.add_argument("--filter", dest="filt", type=Path)
    p.add_argument("--out", type=Path)
    p.add_argument("--project", default="")
    p.add_argument("--cap-per-summary", type=int, default=250)
    p.add_argument("--strict-caps", action="store_true")
    args = p.parse_args(argv)
    if args.check:
        rows = read_jsonl(args.check)
        return check_hard(
            rows,
            strict_caps=args.strict_caps,
            project=args.project or "x",
            cap=args.cap_per_summary,
        )
    if args.filt:
        if not args.out:
            print("quality: --filter needs --out", file=sys.stderr)
            return 2
        rows = read_jsonl(args.filt)
        kept, drops = run_filter(
            rows,
            project=args.project or "x",
            cap=args.cap_per_summary,
            enforce_shape=True,
        )
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("w", encoding="utf-8") as f:
            for row in kept:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(
            "quality: "
            + " ".join(f"{k}={v}" for k, v in drops.items())
            + f" keep={len(kept)} -> {args.out}"
        )
        return 0
    p.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
