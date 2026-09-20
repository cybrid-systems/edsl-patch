#!/usr/bin/env python3
"""Resolve farm/collect session budgets and print usage estimates.

Host farm (Aura apply + cartesian rebind) does not call an LLM.
Grok Build tokens are spent only when an agent implements issues or
extends catalog/projects/<id>/ after catalog-exhausted.

Default preset is smoke. Auto never selects full.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV = ROOT / "catalog" / "projects" / "budget.default.env"
LOCAL_ENV = ROOT / "catalog" / "projects" / "budget.env"
FARM_DIR = ROOT / "data" / "raw" / "farm"
COLLECT_OUT = ROOT / "data" / "raw" / "business.jsonl"
CATALOG = ROOT / "catalog" / "projects"

# bytes / tokens are planning estimates, not billing.
BYTES_PER_FARM_ROW = 520
BYTES_PER_COLLECT_ROW = 800
KEEP_YIELD = 0.45  # kept / attempted after quality filters
AURA_MS_PER_ATTEMPT = 120

# Grok Build token bands (±3×). Host-only farm is 0.
TOKENS_IMPLEMENT_ISSUE = 400_000
TOKENS_PER_CATALOG_EDIT = 80_000
TOKENS_PER_LOOP_OVERHEAD = 40_000
WEEKLY_WARN_TOKENS = 1_500_000

PRESETS: dict[str, dict[str, int | str]] = {
    "off": {
        "target": 0,
        "max_loop": 0,
        "wall_seconds": 0,
        "max_catalog_edits": 0,
        "collect_limit": 0,
        "intent": "refuse to start",
    },
    "smoke": {
        "target": 20,
        "max_loop": 1,
        "wall_seconds": 180,
        "max_catalog_edits": 0,
        "collect_limit": 5,
        "intent": "prove runner; default",
    },
    "small": {
        "target": 80,
        "max_loop": 2,
        "wall_seconds": 600,
        "max_catalog_edits": 5,
        "collect_limit": 25,
        "intent": "one cheap session",
    },
    "medium": {
        "target": 400,
        "max_loop": 4,
        "wall_seconds": 1800,
        "max_catalog_edits": 12,
        "collect_limit": 80,
        "intent": "half-evening host farm + few catalog edits",
    },
    "full": {
        "target": 3000,
        "max_loop": 8,
        "wall_seconds": 7200,
        "max_catalog_edits": 40,
        "collect_limit": 200,
        "intent": "opt-in only; never auto",
    },
}

PROJECT_IDS = (
    "arith-core",
    "pred-if",
    "helper-mod",
    "list-fp",
    "kv-mini",
    "span-aether",
    "circ-dae",
    "orch-pure",
)

ENV_KEYS = {
    "preset": "EDSL_PATCH_BUDGET",
    "target": "FARM_TARGET",
    "max_loop": "FARM_MAX_LOOP",
    "wall_seconds": "FARM_WALL_SECONDS",
    "max_catalog_edits": "FARM_MAX_CATALOG_EDITS",
    "collect_limit": "COLLECT_LIMIT",
}


def _parse_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        out[key.strip()] = val.strip().strip("'\"")
    return out


def _as_int(val: Any, default: int) -> int:
    if val is None or val == "":
        return default
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def load_layers() -> dict[str, str]:
    """File defaults, then local override, then process env."""
    merged: dict[str, str] = {}
    merged.update(_parse_env_file(DEFAULT_ENV))
    merged.update(_parse_env_file(LOCAL_ENV))
    for key in (
        "EDSL_PATCH_BUDGET",
        "FARM_TARGET",
        "FARM_MAX_LOOP",
        "FARM_WALL_SECONDS",
        "FARM_MAX_CATALOG_EDITS",
        "COLLECT_LIMIT",
    ):
        if key in os.environ and os.environ[key] != "":
            merged[key] = os.environ[key]
    return merged


def resolve(
    *,
    preset: str | None = None,
    target: int | None = None,
    max_loop: int | None = None,
    wall_seconds: int | None = None,
    max_catalog_edits: int | None = None,
    collect_limit: int | None = None,
    allow_full: bool = False,
) -> dict[str, Any]:
    layers = load_layers()
    name = (preset or layers.get("EDSL_PATCH_BUDGET") or "smoke").strip().lower()
    if name not in PRESETS:
        raise SystemExit(f"unknown budget preset: {name!r} (want {', '.join(PRESETS)})")
    if name == "full" and not allow_full and (preset is None):
        allow_full = True
    if name == "full" and not allow_full:
        name = "smoke"
    base = dict(PRESETS[name])

    def pick(cli: int | None, env_key: str, fallback: int) -> int:
        if cli is not None:
            return int(cli)
        if env_key in os.environ and os.environ[env_key] != "":
            return _as_int(os.environ[env_key], fallback)
        local = _parse_env_file(LOCAL_ENV)
        if env_key in local:
            return _as_int(local[env_key], fallback)
        return fallback

    src = {
        "preset": name,
        "target": pick(target, "FARM_TARGET", int(base["target"])),
        "max_loop": pick(max_loop, "FARM_MAX_LOOP", int(base["max_loop"])),
        "wall_seconds": pick(wall_seconds, "FARM_WALL_SECONDS", int(base["wall_seconds"])),
        "max_catalog_edits": pick(max_catalog_edits, "FARM_MAX_CATALOG_EDITS", int(base["max_catalog_edits"])),
        "collect_limit": pick(collect_limit, "COLLECT_LIMIT", int(base["collect_limit"])),
    }
    src["target"] = min(int(src["target"]), int(base["target"])) if name != "full" else int(src["target"])
    if name != "full":
        src["max_loop"] = min(int(src["max_loop"]), int(base["max_loop"]))
        src["wall_seconds"] = min(int(src["wall_seconds"]), int(base["wall_seconds"]))
        src["max_catalog_edits"] = min(int(src["max_catalog_edits"]), int(base["max_catalog_edits"]))
        src["collect_limit"] = min(int(src["collect_limit"]), int(base["collect_limit"]))
    src["intent"] = base["intent"]
    src["clamped_from"] = name
    return src


def _count_jsonl(path: Path) -> int:
    if not path.is_file():
        return 0
    n = 0
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                n += 1
    return n


def _catalog_pairs(project: str) -> tuple[int, int, int]:
    d = CATALOG / project
    plants = _count_jsonl(d / "plants.jsonl")
    rewrites = _count_jsonl(d / "rewrites.jsonl")
    return plants, rewrites, plants * rewrites


def _keep_count(project: str) -> int:
    return _count_jsonl(FARM_DIR / f"{project}.jsonl")


def estimate_host(target: int, unused_pairs: int) -> dict[str, Any]:
    usable = max(int(unused_pairs), 0)
    wish = max(int(target), 0)
    will_keep = min(wish, usable)
    attempts = int(will_keep / KEEP_YIELD) if will_keep else 0
    wall_s = attempts * AURA_MS_PER_ATTEMPT / 1000.0
    bytes_out = will_keep * BYTES_PER_FARM_ROW
    return {
        "keep_est": will_keep,
        "attempts_est": attempts,
        "host_seconds_est": round(wall_s, 1),
        "jsonl_bytes_est": bytes_out,
        "jsonl_kib_est": round(bytes_out / 1024, 2),
    }


def estimate_grok(budget: dict[str, Any], *, need_implement: bool, catalog_edits: int) -> dict[str, Any]:
    tokens = 0
    if need_implement:
        tokens += TOKENS_IMPLEMENT_ISSUE
    tokens += int(catalog_edits) * TOKENS_PER_CATALOG_EDIT
    tokens += int(budget["max_loop"]) * TOKENS_PER_LOOP_OVERHEAD
    if int(budget["max_catalog_edits"]) == 0 and not need_implement:
        tokens = 0
    return {
        "grok_tokens_est": tokens,
        "grok_tokens_lo": int(tokens / 3),
        "grok_tokens_hi": tokens * 3,
        "weekly_warn": tokens >= WEEKLY_WARN_TOKENS,
        "host_only": tokens == 0,
    }


def plan_project(project: str, budget: dict[str, Any] | None = None) -> dict[str, Any]:
    if project not in PROJECT_IDS:
        raise SystemExit(f"unknown project {project!r}; known: {', '.join(PROJECT_IDS)}")
    budget = budget or resolve()
    plants, rewrites, pairs = _catalog_pairs(project)
    keep = _keep_count(project)
    remaining = max(int(budget["target"]) - keep, 0)
    unused = max(pairs - keep, 0)
    runner = (ROOT / "scripts" / "farm_project.py").is_file()
    need_implement = not runner or plants == 0
    if need_implement:
        auto = "smoke"
        reason = "missing-runner-or-catalog"
    elif remaining <= 0:
        auto = "off"
        reason = "quota-already-met"
    elif unused >= remaining and remaining <= int(PRESETS["smoke"]["target"]):
        auto = "smoke"
        reason = "host-pairs-cover-smoke"
    elif unused >= remaining:
        auto = "small" if remaining <= int(PRESETS["small"]["target"]) else "medium"
        reason = "host-pairs-sufficient"
    elif remaining <= int(PRESETS["small"]["target"]):
        auto = "small"
        reason = "need-few-catalog-edits"
    else:
        auto = "medium"
        reason = "need-catalog-growth-not-full"
    auto_budget = resolve(preset=auto, allow_full=False)
    edits = 0 if unused >= remaining else int(auto_budget["max_catalog_edits"])
    host = estimate_host(min(remaining, int(auto_budget["target"])), unused if unused else pairs)
    grok = estimate_grok(auto_budget, need_implement=need_implement, catalog_edits=edits)
    return {
        "project": project,
        "keep": keep,
        "plants": plants,
        "rewrites": rewrites,
        "pairs": pairs,
        "unused_pairs_est": unused,
        "remaining_to_wish": remaining,
        "auto_preset": auto,
        "auto_reason": reason,
        "budget": auto_budget,
        "host": host,
        "grok": grok,
        "collect_limit": int(auto_budget["collect_limit"]),
        "collect_rows_now": _count_jsonl(COLLECT_OUT),
        "collect_bytes_est": int(auto_budget["collect_limit"]) * BYTES_PER_COLLECT_ROW,
    }


def plan_all(budget: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    plans = [plan_project(p, budget) for p in PROJECT_IDS]
    seen_implement = False
    for p in plans:
        if p["grok"]["grok_tokens_est"] >= TOKENS_IMPLEMENT_ISSUE:
            if seen_implement:
                p["grok"] = estimate_grok(
                    p["budget"],
                    need_implement=False,
                    catalog_edits=0 if p["auto_reason"] == "missing-runner-or-catalog" else int(p["budget"]["max_catalog_edits"]),
                )
            seen_implement = True
    return plans


def status_line(plan: dict[str, Any]) -> str:
    b = plan["budget"]
    return (
        f"FARM_PLAN project={plan['project']} keep={plan['keep']} "
        f"target={b['target']} budget={plan['auto_preset']} "
        f"pairs={plan['pairs']} collect={plan['collect_limit']} "
        f"grok_tokens_est={plan['grok']['grok_tokens_est']} "
        f"reason={plan['auto_reason']}"
    )


def _print_table(plans: list[dict[str, Any]]) -> None:
    print(
        f"{'project':<14} {'keep':>5} {'pairs':>6} {'auto':<8} "
        f"{'keep_est':>8} {'KiB':>7} {'grok_tok':>10} reason"
    )
    for p in plans:
        print(
            f"{p['project']:<14} {p['keep']:>5} {p['pairs']:>6} {p['auto_preset']:<8} "
            f"{p['host']['keep_est']:>8} {p['host']['jsonl_kib_est']:>7} "
            f"{p['grok']['grok_tokens_est']:>10} {p['auto_reason']}"
        )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Farm/collect budget resolver + usage estimates (no LLM)."
    )
    p.add_argument("--preset", "--budget", dest="preset", default=None, help="smoke|small|medium|full|off")
    p.add_argument("--target", type=int, default=None)
    p.add_argument("--max-loop", dest="max_loop", type=int, default=None)
    p.add_argument("--wall-seconds", dest="wall_seconds", type=int, default=None)
    p.add_argument("--max-catalog-edits", dest="max_catalog_edits", type=int, default=None)
    p.add_argument("--collect-limit", dest="collect_limit", type=int, default=None)
    p.add_argument("--allow-full", action="store_true", help="permit preset=full from CLI")
    p.add_argument("--project", default=None, help="one catalog project id")
    p.add_argument("--print", dest="print_budget", action="store_true", help="print resolved budget JSON")
    p.add_argument("--plan", action="store_true", help="auto-pick preset + estimates")
    p.add_argument("--all", action="store_true", help="plan every project")
    p.add_argument("--json", dest="as_json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    allow_full = bool(args.allow_full or (args.preset == "full"))
    budget = resolve(
        preset=args.preset,
        target=args.target,
        max_loop=args.max_loop,
        wall_seconds=args.wall_seconds,
        max_catalog_edits=args.max_catalog_edits,
        collect_limit=args.collect_limit,
        allow_full=allow_full,
    )
    if args.print_budget and not args.plan:
        print(json.dumps(budget, indent=2, sort_keys=True))
        return 0 if budget["preset"] != "off" else 3
    if not args.plan and not args.print_budget:
        args.plan = True
    if args.project:
        plans = [plan_project(args.project, budget if args.preset else None)]
        if args.preset and plans[0]["auto_preset"] != "off":
            plans[0]["auto_preset"] = budget["preset"]
            plans[0]["budget"] = budget
            plans[0]["auto_reason"] = "operator-preset"
    elif args.all or args.plan:
        plans = plan_all(budget if args.preset else None)
    else:
        plans = plan_all()
    if args.as_json:
        print(json.dumps(plans if len(plans) != 1 else plans[0], indent=2))
    else:
        _print_table(plans)
        print()
        for p in plans:
            print(status_line(p))
    if any(p["grok"]["weekly_warn"] for p in plans):
        print("WARN estimated Grok tokens exceed weekly-warn band; split sessions.", file=sys.stderr)
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
