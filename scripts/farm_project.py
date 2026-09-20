#!/usr/bin/env python3
"""Quota runner: one project shard, one Aura process, star-mode.

See catalog/projects/<id>/README.md. Stop at quota or budget, whichever first.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from apply import pick_bin
from catalog import list_projects, load_project, project_pairs
from edsl_patch import PatchError
from farm import emit_driver, parse_stdout, run_aura, seen_ids, append_jsonl
from farm_budget import resolve
from quality import filter_reason, inspect, sample_key, shape_class


def make_id(project: str, plant: dict, rw: dict, name: str) -> str:
    base = f"farm-{project}-{plant['id']}-{rw['id']}-{name}"
    h = hashlib.sha1(base.encode()).hexdigest()[:8]
    return f"{base}-{h}"


def main(argv: list[str] | None = None) -> int:
    known = list_projects()
    p = argparse.ArgumentParser(
        description=__doc__,
        epilog="Project README: catalog/projects/<id>/README.md",
    )
    p.add_argument("--project", required=True, help="id; see catalog/projects/<id>/README.md")
    p.add_argument("--target", type=int, default=None)
    p.add_argument("--budget", default=None)
    p.add_argument("--cap-per-summary", type=int, default=250)
    p.add_argument("--max-attempts", type=int, default=20000)
    p.add_argument("--timeout", type=int, default=1800)
    p.add_argument("--out", type=Path, default=None)
    p.add_argument("--observe", type=Path, default=None)
    args = p.parse_args(argv)

    if args.project not in known:
        print(
            f"error: unknown project {args.project!r}; known: {', '.join(known) or '(none)'}",
            file=sys.stderr,
        )
        return 2

    allow_full = (args.budget or "").lower() == "full"
    bud = resolve(preset=args.budget, target=args.target, allow_full=allow_full)
    target = min(int(args.target or bud["target"]), int(bud["target"]))
    if args.target and args.target > bud["target"]:
        print(f"farm_project: clamp target {args.target} -> {target} budget={bud['preset']}")

    out = args.out or (ROOT / "data" / "raw" / "farm" / f"{args.project}.jsonl")
    observe_path = args.observe or (
        ROOT / "data" / "raw" / "farm" / f"{args.project}.observe.jsonl"
    )

    try:
        pick_bin()
    except SystemExit as e:
        print(str(e), file=sys.stderr)
        return 1

    plants, rewrites = load_project(args.project)
    plan = project_pairs(plants, rewrites)
    seen = seen_ids(out)
    if len(seen) >= target:
        print(
            f"FARM_PROJECT project={args.project} keep={len(seen)} "
            f"target={target} budget={bud['preset']} reason=quota"
        )
        return 0
    unused = []
    for plant, rw, name in plan:
        sid = make_id(args.project, plant, rw, name)
        if sid not in seen:
            unused.append((plant, rw, name, sid))
    if not unused:
        print(
            f"FARM_PROJECT project={args.project} keep={len(seen)} "
            f"target={target} reason=catalog-exhausted"
        )
        return 0

    unused = unused[: args.max_attempts]
    t0 = time.monotonic()
    try:
        stdout = run_aura(
            emit_driver([(a, b, c) for a, b, c, _ in unused], mode="star"),
            timeout=args.timeout,
        )
    except PatchError as e:
        if "timeout" in str(e):
            print(
                f"FARM_PROJECT project={args.project} keep=0 target={target} reason=timeout"
            )
            return 0
        print(f"farm_project: {e}", file=sys.stderr)
        return 1

    samples, observes = parse_stdout(stdout)
    for ob in observes:
        append_jsonl(observe_path, ob)

    summary_counts: dict[tuple[str, str], int] = {}
    shape_counts: dict[str, int] = {}
    keys: set[str] = set()
    if out.is_file():
        for line in out.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            src, name, body, summary = inspect(row)
            keys.add(sample_key(src, name, body))
            summary_counts[(args.project, summary)] = (
                summary_counts.get((args.project, summary), 0) + 1
            )
            shape_counts[shape_class(body)] = shape_counts.get(shape_class(body), 0) + 1

    keep = 0
    sid_i = 0
    plants_by_id = {pl["id"]: pl for pl in plants}
    for plant_id, row in samples:
        if len(seen) >= target:
            break
        if sid_i >= len(unused):
            break
        plant, rw, name, sid = unused[sid_i]
        sid_i += 1
        if plant_id and plant_id != plant["id"] and plant_id in plants_by_id:
            pass
        row["id"] = sid
        if sid in seen:
            continue
        why = filter_reason(
            row,
            project=args.project,
            cap_per_summary=args.cap_per_summary,
            summary_counts=summary_counts,
            seen=keys,
            shape_counts=shape_counts,
            kept=keep + len(seen),
            enforce_shape=True,
        )
        if why:
            continue
        src, nm, body, summary = inspect(row)
        keys.add(sample_key(src, nm, body))
        summary_counts[(args.project, summary)] = (
            summary_counts.get((args.project, summary), 0) + 1
        )
        shape_counts[shape_class(body)] = shape_counts.get(shape_class(body), 0) + 1
        append_jsonl(out, row)
        seen.add(sid)
        keep += 1

    elapsed = time.monotonic() - t0
    attempts = max(len(samples) + len(observes), 1)
    total_keep = len(seen)
    if keep + (total_keep - keep) >= target or total_keep >= target:
        reason = "quota"
    elif len(observes) / attempts > 0.6 and attempts >= 200:
        reason = "observe-flood"
    elif sid_i >= len(unused) and total_keep < target:
        reason = "catalog-exhausted"
    elif elapsed >= args.timeout:
        reason = "timeout"
    else:
        reason = "attempts" if total_keep < target else "quota"

    print(
        f"FARM_PROJECT project={args.project} keep={total_keep} "
        f"target={target} budget={bud['preset']} reason={reason}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
