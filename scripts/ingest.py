#!/usr/bin/env python3
"""Build apply-verified samples from a synthetic catalog and Strand traces."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from apply import apply_patch
from edsl_patch import PatchError, load_sample, sources_match, validate_patch

SYNTH_BODIES = (
    ("identity", "(lambda (x) x)"),
    ("plus1", "(lambda (x) (+ x 1))"),
    ("negate", "(lambda (x) (* x -1))"),
    ("double", "(lambda (x) (* x 2))"),
    ("abs", "(lambda (x) (if (< x 0) (* x -1) x))"),
)
NAMES = ("f", "g", "h")


def sample_for(name: str, src_body: str, dst_label: str, dst_body: str) -> dict:
    source = f"(define {name} {src_body})"
    expected = f"(define {name} {dst_body})"
    target = [
        {"kind": "query", "op": "find", "name": name},
        {"kind": "query", "op": "def-use", "name": name},
        {
            "kind": "synthesis",
            "op": "rebind",
            "name": name,
            "body": dst_body,
            "summary": dst_label,
        },
    ]
    validate_patch(target)
    return {
        "id": f"{name}-{dst_label}",
        "input": {"source": source},
        "target": target,
        "verify": {"apply_ok": True, "expected_source": expected},
    }


def synthetic_catalog() -> list[dict]:
    rows = []
    for name in NAMES:
        for src_label, src_body in SYNTH_BODIES:
            for dst_label, dst_body in SYNTH_BODIES:
                if src_body == dst_body:
                    continue
                sample = sample_for(name, src_body, dst_label, dst_body)
                sample["id"] = f"{name}-{src_label}-to-{dst_label}"
                rows.append(sample)
    return rows


def from_strand_trace(path: Path) -> list[dict]:
    rows = []
    default_src = "(define f (lambda (x) x))"
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        post_fit = (rec.get("post") or {}).get("fitness")
        pre_fit = (rec.get("observe") or {}).get("fitness")
        label = rec.get("label") or {}
        if label.get("op") != "rebind":
            continue
        if not isinstance(pre_fit, (int, float)) or not isinstance(post_fit, (int, float)):
            continue
        if post_fit <= pre_fit:
            continue
        name = label.get("name")
        body = label.get("body")
        summary = label.get("summary") or "rebind"
        source = (rec.get("observe") or {}).get("source") or default_src
        if not isinstance(name, str) or not isinstance(body, str):
            continue
        sample = {
            "id": f"strand-r{rec.get('round', 0)}-{name}-{summary}",
            "input": {"source": source},
            "target": [
                {"kind": "query", "op": "find", "name": name},
                {
                    "kind": "synthesis",
                    "op": "rebind",
                    "name": name,
                    "body": body,
                    "summary": summary,
                },
            ],
            "verify": {
                "apply_ok": True,
                "expected_source": f"(define {name} {body})",
            },
        }
        try:
            validate_patch(sample["target"])
        except PatchError:
            continue
        rows.append(sample)
    return rows


def verify_row(sample: dict, *, run_host: bool) -> dict | None:
    try:
        load_sample(sample)
    except PatchError:
        return None
    if not run_host:
        sample = dict(sample)
        sample.setdefault("verify", {})["apply_ok"] = False
        sample["verify"]["skipped_host"] = True
        return sample
    try:
        result = apply_patch(sample["input"]["source"], sample["target"])
    except PatchError:
        return None
    expected = (sample.get("verify") or {}).get("expected_source")
    ok = bool(result.get("ok"))
    if expected:
        ok = ok and sources_match(result.get("source") or "", expected)
    if not ok:
        return None
    sample = dict(sample)
    sample["verify"] = {
        "apply_ok": True,
        "expected_source": result.get("source") or expected,
    }
    return sample


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", type=Path, default=ROOT / "data" / "raw" / "verified.jsonl")
    p.add_argument("--no-host", action="store_true", help="skip Aura apply (legal-only)")
    p.add_argument(
        "--strand",
        type=Path,
        default=ROOT / "examples" / "legacy-control" / "strand-r3-poison.jsonl",
    )
    args = p.parse_args(argv)

    candidates = synthetic_catalog()
    if args.strand.is_file():
        candidates.extend(from_strand_trace(args.strand))

    kept = []
    for sample in candidates:
        row = verify_row(sample, run_host=not args.no_host)
        if row is not None:
            kept.append(row)

    write_jsonl(args.out, kept)
    print(f"ingest: kept {len(kept)} / {len(candidates)} -> {args.out}")
    return 0 if kept else 1


if __name__ == "__main__":
    raise SystemExit(main())
