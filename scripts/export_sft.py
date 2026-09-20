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


COMMERCIAL_SHARE = {
    "twin": 0.40,
    "session": 0.20,
    "refuse": 0.20,
    "dialect": 0.15,
    "teacher": 0.05,
}


def to_sft(sample: dict) -> dict:
    source = sample.get("input", {}).get("source")
    if not isinstance(source, str) or not source.strip():
        raise PatchError("missing input.source")
    observe = sample.get("input", {}).get("observe")
    target = validate_patch(sample.get("target"), observe=observe if isinstance(observe, dict) else None)
    user = source.strip()
    intent = (sample.get("input") or {}).get("intent")
    if intent:
        user += "\nintent: " + str(intent)
    if observe:
        user += "\nobserve: " + json.dumps(observe, ensure_ascii=False)
    return {
        "messages": [
            {"role": "system", "content": SYSTEM_CONTRACT.strip()},
            {"role": "user", "content": user},
            {"role": "assistant", "content": json.dumps(target, ensure_ascii=False)},
        ]
    }


MAX_SOURCE_CHARS = 1500


def drop_reason(sample: dict) -> str | None:
    if sample.get("sft") is False:
        return "sft-false"
    src = (sample.get("input") or {}).get("source") or ""
    if len(src) > MAX_SOURCE_CHARS:
        return "source-too-long"
    if (sample.get("verify") or {}).get("apply_ok") is False:
        return "apply_ok-false"
    target = sample.get("target") or []
    for step in target:
        if step.get("kind") in ("skip", "persist", "restore", "yield", "heal"):
            return "control-policy"
        if step.get("kind") == "synthesis" and step.get("op") == "rebind":
            body = step.get("body") or ""
            for tok in ("eval", "fiber:spawn", "synthesize:define"):
                if tok in body:
                    return "illegal-body"
    probes = (sample.get("verify") or {}).get("probes") or {}
    observe = (sample.get("input") or {}).get("observe") or {}
    frozen = list(observe.get("frozen") or [])
    last = target[-1] if target else {}
    if "step" in frozen and last.get("kind") == "synthesis" and not probes.get("t_mono"):
        return "twin-missing-t_mono"
    if "*session*" in frozen and last.get("kind") == "synthesis" and not observe.get("session"):
        return "session-missing"
    try:
        validate_patch(target, observe=observe if isinstance(observe, dict) else None)
    except PatchError:
        return "schema"
    return None


def bucket_of(path: Path, sample: dict) -> str:
    n = path.name.lower()
    tgt = sample.get("target") or []
    last = tgt[-1] if tgt else {}
    if last.get("kind") == "refuse" or "refuse" in n:
        return "refuse"
    if "twin" in n:
        return "twin"
    if "session" in n:
        return "session"
    if "teacher" in n or "business" in n:
        return "teacher"
    return "dialect"


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
    p.add_argument(
        "--profile",
        default="dialect",
        choices=("dialect", "commercial"),
        help="dialect=flat concat (default); commercial=weighted mix",
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
            why = drop_reason(sample)
            if why:
                skipped += 1
                continue
            try:
                rows.append(to_sft(sample) | {"_bucket": bucket_of(path, sample)})
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

    if args.profile == "commercial":
        by: dict[str, list] = {k: [] for k in COMMERCIAL_SHARE}
        for row in rows:
            by.setdefault(row.get("_bucket") or "dialect", []).append(row)
        empty = [k for k, v in COMMERCIAL_SHARE.items() if not by.get(k)]
        if empty:
            print(f"export: warning empty commercial buckets {empty}", file=sys.stderr)
        mixed = []
        taken = {}
        # Never downsample verticals (twin/session/refuse); they are the scarce commercial signal.
        for k in ("twin", "session", "refuse"):
            bucket = by.get(k) or []
            mixed.extend(bucket)
            taken[k] = len(bucket)
        n_vert = sum(taken.get(k, 0) for k in ("twin", "session", "refuse"))
        from collections import defaultdict

        def pick_diverse(bucket: list, take: int) -> list:
            groups: dict[str, list] = defaultdict(list)
            for item in bucket:
                asst = (item.get("messages") or [{}, {}, {}])[2].get("content") or ""
                groups[asst[80:140] if asst else "x"].append(item)
            picked = []
            keys = list(groups) or ["x"]
            i = 0
            while len(picked) < take and any(groups.values()):
                g = keys[i % len(keys)]
                if groups[g]:
                    picked.append(groups[g].pop(0))
                i += 1
                if i > take * max(len(keys), 1) + 20:
                    break
            return picked[:take]

        for k, share in (("dialect", 0.15), ("teacher", 0.05)):
            bucket = by.get(k) or []
            take = min(len(bucket), max(0, int(n_vert * share / 0.80))) if n_vert else min(len(bucket), 1)
            picked = pick_diverse(bucket, take) if k == "dialect" else bucket[:take]
            mixed.extend(picked)
            taken[k] = len(picked)
        rows = mixed
        n = max(len(rows), 1)
        shares = " ".join(f"{k}={taken.get(k, 0)}({100*taken.get(k, 0)/n:.0f}%)" for k in COMMERCIAL_SHARE)
        print(f"export: profile=commercial {shares} n={n}")
        if taken.get("twin", 0) / n < 0.15:
            print("export: warning twin share < 15% (world farm keep rate)", file=sys.stderr)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as f:
        for row in rows:
            row = dict(row)
            row.pop("_bucket", None)
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"export: {len(rows)} sft rows ({skipped} skipped) -> {args.out}")
    return 0 if rows else 1


if __name__ == "__main__":
    raise SystemExit(main())
