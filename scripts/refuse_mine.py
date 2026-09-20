#!/usr/bin/env python3
"""Mine frozen/capability refuse golds. Smoke cap 20. No mutate."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from catalog import load_project
from edsl_patch import validate_patch

OUT = ROOT / "data" / "raw" / "refuse.jsonl"


def emit(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", type=Path, default=OUT)
    p.add_argument("--cap", type=int, default=20)
    args = p.parse_args(argv)
    if args.out.is_file():
        args.out.unlink()
    n = 0
    plants, _ = load_project("twin-step")
    for plant in plants:
        if n >= args.cap:
            break
        for frozen, why in (("step", "integrator is frozen"), ("energy", "energy is read-only")):
            row = {
                "id": f"refuse-frozen-{plant['id']}-{frozen}",
                "input": {
                    "source": plant["source"],
                    "intent": f"rewrite {frozen}",
                    "observe": {"hot": ["control"], "frozen": ["step", "energy"]},
                },
                "target": [
                    {"kind": "query", "op": "find", "name": frozen},
                    {"kind": "refuse", "op": "frozen", "name": frozen, "why": why},
                ],
                "verify": {"apply_ok": True, "unchanged": [frozen]},
                "sft": True,
            }
            validate_patch(row["target"], observe=row["input"]["observe"])
            emit(args.out, row)
            n += 1
            if n >= args.cap:
                break
    plants2, _ = load_project("session-hot")
    for plant in plants2:
        if n >= args.cap:
            break
        row = {
            "id": f"refuse-frozen-{plant['id']}-session",
            "input": {
                "source": plant["source"],
                "intent": "rebind session identity",
                "observe": {"hot": ["quote"], "frozen": ["*session*"]},
            },
            "target": [
                {"kind": "query", "op": "find", "name": "*session*"},
                {
                    "kind": "refuse",
                    "op": "frozen",
                    "name": "*session*",
                    "why": "session identity is frozen",
                },
            ],
            "verify": {"apply_ok": True, "unchanged": ["*session*"]},
            "sft": True,
        }
        validate_patch(row["target"], observe=row["input"]["observe"])
        emit(args.out, row)
        n += 1
    for i, (why, op) in enumerate(
        (
            ("illegal token eval", "capability"),
            ("illegal token c-load", "capability"),
            ("illegal token fiber:spawn", "capability"),
            ("illegal token synthesize:define", "capability"),
            ("extra top-level define", "schema"),
        )
    ):
        if n >= args.cap:
            break
        row = {
            "id": f"refuse-cap-{i}",
            "input": {
                "source": "(define f (lambda (x) x))",
                "intent": why,
                "observe": {"hot": ["f"], "frozen": []},
            },
            "target": [
                {"kind": "query", "op": "find", "name": "f"},
                {"kind": "refuse", "op": op, "name": "f", "why": why},
            ],
            "verify": {"apply_ok": True, "unchanged": ["f"]},
            "sft": True,
        }
        validate_patch(row["target"])
        emit(args.out, row)
        n += 1
    print(f"refuse_mine: wrote {n} (cap {args.cap}) -> {args.out}")
    return 0 if n >= 2 else 1


if __name__ == "__main__":
    raise SystemExit(main())
