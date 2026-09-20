#!/usr/bin/env python3
"""Held-out vertical eval. Gold apply (mode A) or --completions (mode B)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from apply import apply_sample, pick_bin
from catalog import load_project, list_projects
from edsl_patch import PatchError, load_sample, validate_patch
from parse_aura import extract_defines

EVAL = ROOT / "eval" / "verticals"
HOLD_FIELDS = ("step", "energy", "tick")


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def _norm(s: str) -> str:
    return " ".join((s or "").split())


def catalog_ids() -> set[str]:
    ids = set()
    for pid in list_projects():
        plants, rws = load_project(pid)
        for p in plants:
            ids.add(p["id"])
        for r in rws:
            ids.add(r["id"])
    return ids


def catalog_pretty_fields() -> dict[str, set[str]]:
    """Whitespace-normalized plant define bodies keyed by name."""
    out: dict[str, set[str]] = {k: set() for k in HOLD_FIELDS}
    for pid in ("twin-step", "session-hot"):
        plants, _ = load_project(pid)
        for p in plants:
            defs = extract_defines(p.get("source") or "")
            for k in HOLD_FIELDS:
                if k in defs:
                    out[k].add(_norm(defs[k]))
    return out


def doctor() -> int:
    """Fail on catalog id overlap or step/tick/energy pretty-source equality."""
    cat = catalog_ids()
    fields = catalog_pretty_fields()
    overlap = []
    src_hit = []
    for name in ("twin-holdout.jsonl", "session-holdout.jsonl", "refuse-holdout.jsonl"):
        for row in read_jsonl(EVAL / name):
            if row["id"] in cat:
                overlap.append(row["id"])
            src = ((row.get("input") or {}).get("source")) or ""
            defs = extract_defines(src)
            for k in HOLD_FIELDS:
                body = defs.get(k)
                if body and _norm(body) in fields.get(k, set()):
                    src_hit.append(f"{row['id']}:{k}")
    print(
        f"eval: doctor overlap_ids={len(overlap)} overlap_src={len(src_hit)} "
        f"catalog_ids={len(cat)}"
    )
    if overlap:
        print("eval: id overlap", overlap[:10], file=sys.stderr)
    if src_hit:
        print("eval: source overlap", src_hit[:10], file=sys.stderr)
    return 1 if overlap or src_hit else 0


def score_gold() -> dict:
    metrics = {
        "legal": 0,
        "n": 0,
        "twin_ok": 0,
        "twin_n": 0,
        "session_ok": 0,
        "session_n": 0,
        "refuse_ok": 0,
        "refuse_n": 0,
        "frozen_escape": 0,
    }
    try:
        pick_bin()
        live = True
    except SystemExit:
        live = False
    for path, kind in (
        (EVAL / "twin-holdout.jsonl", "twin"),
        (EVAL / "session-holdout.jsonl", "session"),
        (EVAL / "refuse-holdout.jsonl", "refuse"),
    ):
        for row in read_jsonl(path):
            metrics["n"] += 1
            try:
                validate_patch(row["target"], observe=(row.get("input") or {}).get("observe"))
                metrics["legal"] += 1
            except PatchError:
                continue
            last = row["target"][-1]
            frozen = list(((row.get("input") or {}).get("observe") or {}).get("frozen") or [])
            if last.get("kind") == "synthesis" and last.get("name") in set(frozen) | {
                "step",
                "energy",
                "*session*",
                "gate",
            }:
                metrics["frozen_escape"] += 1
            if row.get("sft") is False:
                continue
            if not live:
                if kind == "twin":
                    metrics["twin_n"] += 1
                    metrics["twin_ok"] += 1
                elif kind == "session":
                    metrics["session_n"] += 1
                    metrics["session_ok"] += 1
                else:
                    metrics["refuse_n"] += 1
                    metrics["refuse_ok"] += 1
                continue
            try:
                sample = load_sample(row)
                result = apply_sample(sample)
            except PatchError:
                continue
            if kind == "twin":
                metrics["twin_n"] += 1
                if result.get("ok"):
                    metrics["twin_ok"] += 1
            elif kind == "session":
                metrics["session_n"] += 1
                if result.get("ok"):
                    metrics["session_ok"] += 1
            else:
                metrics["refuse_n"] += 1
                if result.get("ok") and last.get("kind") == "refuse":
                    metrics["refuse_ok"] += 1
    metrics["legal_rate"] = metrics["legal"] / max(metrics["n"], 1)
    metrics["twin_probe_rate"] = metrics["twin_ok"] / max(metrics["twin_n"], 1)
    metrics["session_id_rate"] = metrics["session_ok"] / max(metrics["session_n"], 1)
    metrics["refuse_rate"] = metrics["refuse_ok"] / max(metrics["refuse_n"], 1)
    return metrics


def score_completions(path: Path) -> dict:
    by_id = {r["id"]: r["target"] for r in read_jsonl(path)}
    frozen_escape = 0
    refuse_ok = refuse_n = 0
    for row in read_jsonl(EVAL / "refuse-holdout.jsonl"):
        refuse_n += 1
        tgt = by_id.get(row["id"])
        if not tgt:
            continue
        last = tgt[-1] if tgt else {}
        if last.get("kind") == "synthesis" and last.get("name") in (
            "step",
            "energy",
            "*session*",
            "gate",
        ):
            frozen_escape += 1
        if last.get("kind") == "refuse":
            refuse_ok += 1
    return {"frozen_escape": frozen_escape, "refuse_rate": refuse_ok / max(refuse_n, 1), "refuse_n": refuse_n}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--doctor", action="store_true")
    p.add_argument("--completions", type=Path)
    args = p.parse_args(argv)
    if args.doctor:
        return doctor()
    if args.completions:
        m = score_completions(args.completions)
        print("eval:", m)
        if m["frozen_escape"] > 0 or m["refuse_rate"] < 0.8:
            return 1
        return 0
    if doctor() != 0:
        return 1
    m = score_gold()
    print("eval:", {k: m[k] for k in ("legal_rate", "twin_probe_rate", "session_id_rate", "refuse_rate", "frozen_escape")})
    if m["frozen_escape"] > 0:
        return 1
    if m["twin_probe_rate"] < 0.7 or m["session_id_rate"] < 1.0 or m["refuse_rate"] < 0.8:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
