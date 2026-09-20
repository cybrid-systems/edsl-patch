#!/usr/bin/env python3
"""Load and legally-check the closed L0/L1 rewrite catalog. No Aura, no LLM."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from edsl_patch import PatchError, validate_patch
from parse_aura import extract_defines, patch_for

PLANTS = ROOT / "catalog" / "plants.jsonl"
REWRITES = ROOT / "catalog" / "rewrites.jsonl"

BANNED = ("define", "eval", "synthesize:define", "fiber:spawn")


def read_jsonl(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def load_plants(path: Path = PLANTS) -> list[dict]:
    return read_jsonl(path)


def load_rewrites(path: Path = REWRITES) -> list[dict]:
    return read_jsonl(path)


def retarget(rewrite: dict, name: str) -> dict:
    out = dict(rewrite)
    out["name"] = name
    return out


def rewrite_patch(rewrite: dict) -> list[dict]:
    return patch_for(rewrite["name"], rewrite["body"], rewrite["summary"])


def dummy_source(name: str) -> str:
    return f"(define {name} (lambda (x) 0))"


def is_noop(plant: dict, rewrite: dict, name: str) -> bool:
    defs = extract_defines(plant["source"])
    body = rewrite["body"]
    return defs.get(name) == body


def check(plants: list[dict], rewrites: list[dict]) -> list[str]:
    errs: list[str] = []
    if len(plants) < 6:
        errs.append(f"need ≥6 plants, got {len(plants)}")
    if len(rewrites) < 8:
        errs.append(f"need ≥8 rewrites, got {len(rewrites)}")
    summaries = []
    ids = []
    for rw in rewrites:
        rid = rw.get("id")
        if not isinstance(rid, str) or not rid:
            errs.append("rewrite missing stable id")
            continue
        if rid in ids:
            errs.append(f"duplicate rewrite id {rid}")
        ids.append(rid)
        body = rw.get("body") or ""
        for tok in BANNED:
            if tok == "define" and "(define" in body:
                errs.append(f"{rid}: body contains define")
            elif tok != "define" and tok in body:
                errs.append(f"{rid}: body contains {tok}")
        try:
            validate_patch(rewrite_patch(rw))
        except PatchError as e:
            errs.append(f"{rid}: {e}")
        dummy = dummy_source(rw["name"])
        try:
            validate_patch(rewrite_patch(rw))
        except PatchError as e:
            errs.append(f"{rid} dummy: {e}")
        summaries.append(rw.get("summary"))
        if extract_defines(dummy).get(rw["name"]) == rw["body"]:
            pass  # dummy is 0; rewrite may equal 0 for summary zero
    if len(set(summaries)) < 8:
        errs.append(f"need ≥8 distinct summaries, got {sorted(set(summaries))}")
    for p in plants:
        names = p.get("names") or []
        if not names:
            errs.append(f"plant {p.get('id')} missing names")
        src = p.get("source") or ""
        if not src.strip():
            errs.append(f"plant {p.get('id')} empty source")
    return errs


def pairs(plants: list[dict], rewrites: list[dict]) -> list[tuple[dict, dict, str]]:
    out = []
    for p in plants:
        for name in p.get("names") or []:
            for rw in rewrites:
                r = retarget(rw, name)
                if is_noop(p, r, name):
                    continue
                out.append((p, r, name))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="legal-only; no Aura")
    ap.add_argument("--plants", type=Path, default=PLANTS)
    ap.add_argument("--rewrites", type=Path, default=REWRITES)
    args = ap.parse_args(argv)
    plants = load_plants(args.plants)
    rewrites = load_rewrites(args.rewrites)
    if args.check:
        errs = check(plants, rewrites)
        if errs:
            for e in errs:
                print(f"catalog: {e}", file=sys.stderr)
            return 1
        n = len(pairs(plants, rewrites))
        print(f"catalog: ok plants={len(plants)} rewrites={len(rewrites)} pairs={n}")
        return 0
    print(f"catalog: plants={len(plants)} rewrites={len(rewrites)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
