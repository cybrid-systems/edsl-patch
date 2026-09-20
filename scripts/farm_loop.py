#!/usr/bin/env python3
"""Re-enterable per-project farm loop. Default budget is smoke, never full.

Env: EDSL_PATCH_BUDGET, FARM_TARGET, FARM_MAX_LOOP, FARM_WALL_SECONDS,
FARM_MAX_CATALOG_EDITS. Do not call /loop. One project per session.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from catalog import list_projects
from farm_budget import resolve
from farm_project import main as farm_project_main


def parse_project_line(text: str) -> dict[str, str]:
    out = {}
    for line in text.splitlines():
        if line.startswith("FARM_PROJECT "):
            for part in line.split():
                if "=" in part:
                    k, _, v = part.partition("=")
                    out[k] = v
    return out


def main(argv: list[str] | None = None) -> int:
    known = list_projects()
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--project", required=True)
    p.add_argument(
        "--budget",
        default=None,
        help="smoke|small|medium|full (default smoke via EDSL_PATCH_BUDGET)",
    )
    p.add_argument("--target", type=int, default=None, help="wish; clamped to preset")
    p.add_argument("--max-loop", type=int, default=None, help="wish; clamped to preset")
    p.add_argument("--wall-seconds", type=int, default=None)
    p.add_argument("--max-catalog-edits", type=int, default=None)
    p.add_argument("--max-attempts", type=int, default=None)
    p.add_argument("--mode", default="star", help="star (dialect) or world (twin-step/session-hot)")
    args = p.parse_args(argv)

    if args.project not in known:
        print(
            f"error: unknown project {args.project!r}; known: {', '.join(known)}",
            file=sys.stderr,
        )
        return 2

    allow_full = (args.budget or "").lower() == "full"
    bud = resolve(
        preset=args.budget,
        target=args.target,
        max_loop=args.max_loop,
        wall_seconds=args.wall_seconds,
        max_catalog_edits=args.max_catalog_edits,
        allow_full=allow_full,
    )
    if bud["preset"] == "off" or int(bud["target"]) <= 0:
        print(
            f"FARM_LOOP project={args.project} keep=0 target=0 "
            f"budget={bud['preset']} loops=0 reason=budget"
        )
        return 0

    if args.target and args.target > bud["target"]:
        print(
            f"farm_loop: clamp target {args.target} -> {bud['target']} "
            f"budget={bud['preset']}"
        )

    target = int(bud["target"])
    max_loop = int(bud["max_loop"])
    wall = int(bud["wall_seconds"])
    t0 = time.monotonic()
    loops = 0
    keep = 0
    reason = "max-loop"
    while loops < max_loop:
        if time.monotonic() - t0 >= wall:
            reason = "wall"
            break
        loops += 1
        if args.mode == "world":
            from farm import main as farm_main

            rounds = args.max_attempts or min(24, int(target))
            outp = ROOT / "data" / "raw" / f"farm-world-{args.project}.jsonl"
            rc = farm_main(
                [
                    "--mode",
                    "world",
                    "--project",
                    args.project,
                    "--rounds",
                    str(rounds),
                    "--timeout",
                    str(min(120, max(30, wall))),
                    "--out",
                    str(outp),
                ]
            )
            if outp.is_file():
                keep = sum(1 for line in outp.read_text().splitlines() if line.strip())
            if keep >= target:
                reason = "quota"
                break
            if rc != 0 and keep == 0:
                reason = "catalog-exhausted"
                break
            continue
        fp_argv = [
            "--project",
            args.project,
            "--target",
            str(target),
            "--budget",
            str(bud["preset"]),
            "--timeout",
            str(args.max_attempts and 90 or min(90, max(30, wall))),
            "--max-attempts",
            str(args.max_attempts or min(60, int(target) + 20)),
        ]
        rc = farm_project_main(fp_argv)
        # farm_project prints FARM_PROJECT; re-run capture via subprocess if needed
        shard = ROOT / "data" / "raw" / "farm" / f"{args.project}.jsonl"
        if shard.is_file():
            keep = sum(1 for line in shard.read_text().splitlines() if line.strip())
        if rc == 2:
            return 2
        if keep >= target:
            reason = "quota" if not (args.target and args.target > target) else "budget"
            break
        # catalog-exhausted: Grok may edit catalog if max_catalog_edits>0
        remaining = int(bud["max_catalog_edits"])
        if remaining <= 0:
            reason = "catalog-exhausted"
            break
        print(
            f"farm_loop: catalog-exhausted; Grok may add ≤{remaining} "
            f"plants/rewrites in catalog/projects/{args.project}/ then re-enter"
        )
        reason = "catalog-exhausted"
        break
    else:
        reason = "max-loop"

    if time.monotonic() - t0 >= wall and keep < target:
        reason = "wall"

    print(
        f"FARM_LOOP project={args.project} keep={keep} target={target} "
        f"budget={bud['preset']} loops={loops} reason={reason}"
    )
    if reason == "catalog-exhausted" and loops >= max_loop:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
