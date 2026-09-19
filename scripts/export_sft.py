#!/usr/bin/env python3
"""Strip verify fields and write chat-format SFT jsonl."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from edsl_patch import SYSTEM_CONTRACT, PatchError, validate_patch


def to_sft(sample: dict) -> dict:
    source = sample.get("input", {}).get("source")
    if not isinstance(source, str) or not source.strip():
        raise PatchError("missing input.source")
    target = validate_patch(sample.get("target"))
    return {
        "messages": [
            {"role": "system", "content": SYSTEM_CONTRACT.strip()},
            {"role": "user", "content": source.strip()},
            {"role": "assistant", "content": json.dumps(target, ensure_ascii=False)},
        ]
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("src", nargs="+", type=Path, help="verified sample jsonl")
    p.add_argument("--out", type=Path, default=ROOT / "data" / "raw" / "sft.jsonl")
    args = p.parse_args(argv)

    rows = []
    skipped = 0
    for path in args.src:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            sample = json.loads(line)
            try:
                rows.append(to_sft(sample))
            except PatchError:
                skipped += 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"export: {len(rows)} sft rows ({skipped} skipped) -> {args.out}")
    return 0 if rows else 1


if __name__ == "__main__":
    raise SystemExit(main())
