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
    n = 0
    # frozen: twin-step step
    plants, _ = load_project("twin-step")
    src = plants[0]["source"]
    row = {
        "id": "refuse-frozen-step",
        "input": {
            "source": src,
            "intent": "rewrite the integrator",
            "observe": {"hot": ["control"], "frozen": ["step", "energy"]},
        },
        "target": [
            {"kind": "query", "op": "find", "name": "step"},
            {"kind": "refuse", "op": "frozen", "name": "step", "why": "integrator is frozen"},
        ],
        "verify": {"apply_ok": True, "unchanged": ["step"]},
        "sft": True,
    }
    validate_patch(row["target"], observe=row["input"]["observe"])
    emit(args.out, row)
    n += 1
    row2 = {
        "id": "refuse-capability-eval",
        "input": {
            "source": "(define f (lambda (x) x))",
            "intent": "eval the argument",
            "observe": {"hot": ["f"], "frozen": []},
        },
        "target": [
            {"kind": "query", "op": "find", "name": "f"},
            {"kind": "refuse", "op": "capability", "name": "f", "why": "illegal token eval"},
        ],
        "verify": {"apply_ok": True, "unchanged": ["f"]},
        "sft": True,
    }
    validate_patch(row2["target"])
    emit(args.out, row2)
    n += 1
    plants2, _ = load_project("session-hot")
    row3 = {
        "id": "refuse-frozen-session",
        "input": {
            "source": plants2[0]["source"],
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
    validate_patch(row3["target"], observe=row3["input"]["observe"])
    emit(args.out, row3)
    n += 1
    print(f"refuse_mine: wrote {n} (cap {args.cap}) -> {args.out}")
    return 0 if n >= 2 else 1


if __name__ == "__main__":
    raise SystemExit(main())
