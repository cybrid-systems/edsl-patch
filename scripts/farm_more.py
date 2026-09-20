#!/usr/bin/env python3
"""Incremental host farm: small Aura batches until target or no progress.

Does not commit data/raw. Default budget is medium (400) when you pass
--budget medium; smoke/small still clamp.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from catalog import list_projects
from farm_project import main as farm_project_main


def count_jsonl(path: Path) -> int:
    if not path.is_file():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--project", default="", help="one id, or empty for all")
    p.add_argument("--budget", default="medium")
    p.add_argument("--target", type=int, default=None)
    p.add_argument("--batch", type=int, default=20)
    p.add_argument("--timeout", type=int, default=50)
    p.add_argument("--rounds", type=int, default=40, help="max batch iterations per project")
    args = p.parse_args(argv)

    ids = [args.project] if args.project else list_projects()
    overall = 0
    for pid in ids:
        out = ROOT / "data" / "raw" / "farm" / f"{pid}.jsonl"
        batch = 5 if pid == "kv-mini" else args.batch
        timeout = 30 if pid == "kv-mini" else args.timeout
        stall = 0
        for i in range(args.rounds):
            before = count_jsonl(out)
            fp = [
                "--project",
                pid,
                "--budget",
                args.budget,
                "--max-attempts",
                str(batch),
                "--timeout",
                str(timeout),
            ]
            if args.target is not None:
                fp.extend(["--target", str(args.target)])
            rc = farm_project_main(fp)
            after = count_jsonl(out)
            print(f"farm_more: {pid} round={i+1} {before}->{after} rc={rc}", flush=True)
            if args.target is not None and after >= args.target:
                break
            if after <= before:
                stall += 1
                if stall >= 3:
                    break
            else:
                stall = 0
        n = count_jsonl(out)
        overall += n
        print(f"farm_more: {pid} total={n}")
    print(f"farm_more: shards={len(ids)} rows={overall}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
