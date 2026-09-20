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


DEFAULT_SRC = (
    ROOT / "data" / "raw" / "verified.jsonl",
    ROOT / "data" / "raw" / "teacher.jsonl",
    ROOT / "data" / "raw" / "business.jsonl",
    ROOT / "data" / "raw" / "farm.jsonl",
)


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


def is_farm_path(path: Path) -> bool:
    return "farm" in path.name.lower()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "src",
        nargs="*",
        type=Path,
        help="verified sample jsonl (default: data/raw/{verified,teacher,business,farm}.jsonl if present)",
    )
    p.add_argument("--out", type=Path, default=ROOT / "data" / "raw" / "sft.jsonl")
    p.add_argument(
        "--cap-farm",
        type=int,
        default=0,
        help="max farm.jsonl rows (0 = no cap)",
    )
    args = p.parse_args(argv)

    srcs = list(args.src) if args.src else [p for p in DEFAULT_SRC if p.is_file()]
    if not srcs:
        print("export: no input jsonl", file=sys.stderr)
        return 1

    rows = []
    skipped = 0
    per_src: dict[str, int] = {}
    farm_kept = 0
    other_kept = 0
    for path in srcs:
        farm = is_farm_path(path)
        farm_n = 0
        n = 0
        if not path.is_file():
            print(f"export: missing {path}", file=sys.stderr)
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            if farm and args.cap_farm > 0 and farm_n >= args.cap_farm:
                break
            sample = json.loads(line)
            try:
                rows.append(to_sft(sample))
            except PatchError:
                skipped += 1
                continue
            n += 1
            if farm:
                farm_n += 1
                farm_kept += 1
            else:
                other_kept += 1
        per_src[str(path)] = n
        print(f"export: {path.name} {n}")

    if farm_kept > 3 * max(other_kept, 1) and other_kept > 0:
        print(
            f"export: warning farm={farm_kept} > 3× other={other_kept}",
            file=sys.stderr,
        )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"export: {len(rows)} sft rows ({skipped} skipped) -> {args.out}")
    return 0 if rows else 1


if __name__ == "__main__":
    raise SystemExit(main())
