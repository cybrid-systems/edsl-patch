#!/usr/bin/env python3
"""Depth-1 EDSL controller loop for arith-core.

One group is K patches for the same source, intent, and observe.
Catalog rewrites or a completions file supply the patches.
Scoring is schema, then snapshot → rebind → eval-current → probe.
advantage = r − mean(r). A hop is SFT gold only when the probe matches
and the advantage is positive. Compile failure is a gate, not the objective.

  python3 scripts/controller.py --project arith-core --plant arith-core.p0 --host dry-world
  python3 scripts/controller.py --project arith-core --plant arith-core.p0 --host aura --forks 8
  python3 scripts/controller.py --project arith-core --plant arith-core.p0 --host aura \\
      --proposer completions --completions candidates.jsonl --export /tmp/arith-sft.jsonl

Completions jsonl, one candidate per line: {"plant":"arith-core.p0","target":[...patch...]}.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import reward as R  # noqa: E402
import rollout as RO  # noqa: E402
import sandbox_world as W  # noqa: E402
from catalog import load_project  # noqa: E402
from edsl_patch import PatchError, validate_patch  # noqa: E402

PROJECT = "arith-core"
HARD_CUTS = ("schema", "rebind", "eval_fail", "identity", "t_break")
GATE_R = {"schema": -20.0, "rebind": -10.0, "eval": -8.0}
# This Aura build's set-code / eval-current entry drops arguments -1 and -2
# (the call returns ()). Other integers, including -3 and a returned -1, pass.
HOST_DROP_ARGS = {-1, -2}


def fit_intent(plant_id: str) -> str:
    return f"fit {plant_id} on the probe grid"


def _dropped_arg(value: Any) -> bool:
    try:
        return int(value) in HOST_DROP_ARGS and float(value) == int(value)
    except (TypeError, ValueError):
        return False


def aura_safe_grid(grid: list, expect: list | None, arity: int) -> tuple[list, list | None]:
    """Drop probe points this host cannot pass into a set-code lambda."""
    if arity == 1:
        keep = [i for i, x in enumerate(grid) if not _dropped_arg(x)]
    else:
        keep = [
            i
            for i, pair in enumerate(grid)
            if not any(_dropped_arg(x) for x in pair)
        ]
    if not keep or len(keep) == len(grid):
        return list(grid), list(expect) if expect is not None else None
    safe_grid = [grid[i] for i in keep]
    safe_expect = None
    if expect is not None:
        safe_expect = [expect[i] for i in keep if i < len(expect)]
    return safe_grid, safe_expect


def score_fork(
    pre: dict[str, Any],
    post: dict[str, Any] | None,
    action: dict[str, Any],
    cfg: dict[str, Any],
    gate: str | None = None,
) -> dict[str, Any]:
    """Probe reward, after hard gates. Unchanged synthesis is an identity cut."""
    if gate == "schema":
        return {"r": GATE_R["schema"], "components": {"gate": GATE_R["schema"]}, "cut": "schema"}
    if gate == "rebind":
        return {"r": GATE_R["rebind"], "components": {"gate": GATE_R["rebind"]}, "cut": "rebind"}
    if gate == "eval":
        return {"r": GATE_R["eval"], "components": {"gate": GATE_R["eval"]}, "cut": "eval_fail"}
    if post is None:
        return {"r": GATE_R["eval"], "components": {"gate": GATE_R["eval"]}, "cut": "eval_fail"}
    rw = R.reward_arith(pre, post, action, cfg)
    if action.get("kind") == "synthesis" and _vals_same(pre.get("vals"), post.get("vals")):
        return {"r": 0.0, "components": {"identity": 0.0}, "cut": "identity"}
    return rw


def mark_sft(adv: float, rw: dict[str, Any], advantage_min: float) -> bool:
    """Gold is an exact probe match that beat the group mean."""
    return adv > advantage_min and rw.get("cut") == ""


def prepare_target(target: Any, observe: dict[str, Any]) -> dict[str, Any]:
    try:
        patch = validate_patch(target, observe=observe)
    except PatchError:
        raw = target if isinstance(target, list) else []
        return {"kind": "schema", "summary": "schema", "target": raw, "gate": "schema"}
    last = patch[-1]
    if last["kind"] == "refuse":
        return {"kind": "refuse", "summary": last["why"], "target": patch}
    return {"kind": "synthesis", "summary": last["summary"], "target": patch}


def load_completion_groups(path: Path, default_plant: str, k: int) -> dict[str, list[Any]]:
    groups: dict[str, list[Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        obj = json.loads(line)
        if not isinstance(obj, dict) or "target" not in obj:
            raise PatchError("completion line needs a target array")
        pid = str(obj.get("plant") or default_plant)
        bucket = groups.setdefault(pid, [])
        if len(bucket) < k:
            bucket.append(obj["target"])
    if not groups:
        raise PatchError(f"no completions in {path}")
    return groups


def _vals_same(a: Any, b: Any) -> bool:
    if not isinstance(a, list) or not isinstance(b, list) or not a or len(a) != len(b):
        return False
    for x, y in zip(a, b):
        if x is False or y is False or x is True or y is True:
            if x is not y:
                return False
            continue
        try:
            if float(x) != float(y):
                return False
        except (TypeError, ValueError):
            if x != y:
                return False
    return True


def _dry_fn(prop: dict[str, Any], rewrites: list[dict]) -> Any:
    if prop.get("kind") != "synthesis":
        return None
    summary = prop.get("summary")
    if summary in W.ARITH_FNS:
        return W.ARITH_FNS[summary]
    body = (prop.get("target") or [{}])[-1].get("body")
    for rw in rewrites:
        if rw.get("body") == body and rw.get("summary") in W.ARITH_FNS:
            return W.ARITH_FNS[rw["summary"]]
    return None


def _observe(plant_id: str, vals: list, name: str, expect: list | None) -> dict[str, Any]:
    obs: dict[str, Any] = {
        "vals": list(vals),
        "ok": bool(vals) and all(v is not None and v is not False for v in vals),
        "plant": plant_id,
        "hot": [name],
        "frozen": [],
        "epoch": 1,
    }
    if expect is not None:
        obs["expect"] = expect
    return obs


def _hop(
    traj_id: str,
    index: int,
    prop: dict[str, Any],
    rw: dict[str, Any],
    adv: float,
    sft: bool,
    source: str,
    intent: str,
    obs_out: dict[str, Any],
    host: str,
    proposer: str,
) -> dict[str, Any]:
    summary = str(prop.get("summary") or "fork")
    cut = rw.get("cut") or ""
    return {
        "id": f"{traj_id}-h1-{index}-{summary}",
        "kind": "hop",
        "fork_id": f"root.{index}",
        "parent_id": "root",
        "hop": 1,
        "input": {"source": source, "intent": intent, "observe": obs_out},
        "target": prop.get("target") or [],
        "reward": {
            "r": rw["r"],
            "advantage": adv,
            "components": rw.get("components") or {},
            "cut": cut,
        },
        "verify": {
            "apply_ok": cut not in ("schema", "rebind", "eval_fail"),
            "probes": {"match": cut == ""},
        },
        "sft": sft,
        "proposer": proposer,
        "host": host,
    }


def _finish(
    plant_id: str,
    props: list[dict],
    rewards: list[dict],
    source: str,
    intent: str,
    obs_out: dict[str, Any],
    host: str,
    proposer: str,
    advantage_min: float,
    traj_cut: str,
) -> tuple[list[dict], dict]:
    advs = RO._adv([rw["r"] for rw in rewards])
    traj_id = f"traj-ctl-{plant_id}"
    hops = []
    for i, (prop, rw, adv) in enumerate(zip(props, rewards, advs)):
        hops.append(
            _hop(
                traj_id,
                i,
                prop,
                rw,
                adv,
                mark_sft(adv, rw, advantage_min),
                source,
                intent,
                obs_out,
                host,
                proposer,
            )
        )
    traj = {
        "id": traj_id,
        "kind": "traj",
        "project": PROJECT,
        "plant": plant_id,
        "host": host,
        "proposer": proposer,
        "hops": [h["id"] for h in hops],
        "return": sum(h["reward"]["r"] for h in hops if h.get("sft")),
        "cut": traj_cut,
    }
    return hops, traj


def group_dry(
    spec: dict,
    meta: dict,
    cfg: dict,
    props: list[dict],
    rewrites: list[dict],
    proposer: str,
) -> tuple[list[dict], dict]:
    plant_id = spec["id"]
    name, arity, fn = meta["name"], meta["arity"], meta["fn"]
    grid = cfg.get("grid2") if arity == 2 else cfg.get("grid", [-3, -1, 0, 1, 2])
    expect = ((cfg.get("plants") or {}).get(plant_id) or {}).get("expect")
    pre_vals = W.arith_grid_vals(fn, grid, arity)
    pre = _observe(plant_id, pre_vals, name, expect)
    rewards = []
    for prop in props:
        gate = prop.get("gate")
        if gate:
            rewards.append(score_fork(pre, None, prop, cfg, gate=gate))
            continue
        if prop.get("kind") == "refuse":
            post_vals = pre_vals
        else:
            nxt = _dry_fn(prop, rewrites)
            if nxt is None:
                rewards.append(score_fork(pre, None, prop, cfg, gate="eval"))
                continue
            post_vals = W.arith_grid_vals(nxt, grid, arity)
        post = _observe(plant_id, post_vals, name, expect)
        post["ok"] = all(v is not None for v in post_vals)
        rewards.append(score_fork(pre, post, prop, cfg))
    obs_out = {k: v for k, v in pre.items() if k != "expect"}
    return _finish(
        plant_id,
        props,
        rewards,
        spec["source"],
        fit_intent(plant_id),
        obs_out,
        "dry-world",
        proposer,
        float(cfg.get("advantage_min", 0.0)),
        "depth",
    )


def emit_controller_hop(
    source: str,
    name: str,
    grid: list,
    props: list[dict],
    arity: int,
) -> str:
    """One depth-1 group. Fork is ast:snapshot. Rebind counts only as #t."""
    if arity == 2:
        pairs = " ".join(f"(list {a} {b})" for a, b in grid)
        grid_form = f"(sandbox:grid2 {name} (list {pairs}))"
    else:
        xs = " ".join(str(x) for x in grid)
        grid_form = f"(sandbox:grid1 {name} (list {xs}))"
    lines = [
        ";; controller depth-1 arith group. Snapshot restore is plumbing.",
        '(require "sandbox" all:)',
        f"(set-code {RO.scheme_string(source)})",
        "(eval-current)",
        '(display "EDSL_OBS ")',
        f'(display (json-encode (hash "epoch" 1 "vals" {grid_form})))',
        "(newline)",
        '(define *snap* (try (ast:snapshot "controller") (catch (e) -1)))',
        "(define *rb* #f)",
        "(define *ev* #f)",
        "(define *vs* #f)",
    ]
    for i, prop in enumerate(props):
        lines += [
            f"(define *fi* {i})",
            "(if (and (number? *snap*) (>= *snap* 0)) (try (ast:restore *snap*) (catch (e) #f)) #f)",
            "(try (eval-current) (catch (e) #f))",
        ]
        if prop.get("kind") == "synthesis":
            tgt = prop["target"][-1]
            lines += [
                "(set! *rb* (try (mutate:rebind "
                f"{RO.scheme_string(tgt['name'])} {RO.scheme_string(tgt['body'])} "
                f"{RO.scheme_string(tgt['summary'])}) (catch (e) #f)))",
                "(set! *rb* (eq? *rb* #t))",
                "(set! *ev* (if *rb* (try (begin (eval-current) #t) (catch (e) #f)) #f))",
            ]
        else:
            lines += ["(set! *rb* #t)", "(set! *ev* #t)"]
        lines += [
            f"(set! *vs* (if (and *rb* *ev*) (try {grid_form} (catch (e) #f)) #f))",
            '(display "EDSL_FORK ")',
            "(display (json-encode (hash \"i\" *fi* \"rb\" *rb* \"ev\" *ev* "
            '"ok" (if (and *rb* *ev* *vs*) #t #f) '
            '"obs" (hash "epoch" 1 "vals" (if *vs* *vs* (quote ()))))))',
            "(newline)",
        ]
    lines.append("")
    driver = "\n".join(lines)
    if "fiber:spawn" in driver:
        raise RuntimeError("fiber:spawn is not the fork")
    return driver


def _fork_gate(fr: dict | None) -> str | None:
    if not fr or fr.get("rb") is not True:
        return "rebind"
    if fr.get("ev") is not True or fr.get("ok") is not True:
        return "eval"
    return None


def group_aura(
    spec: dict,
    meta: dict,
    cfg: dict,
    props: list[dict],
    proposer: str,
) -> tuple[list[dict], dict]:
    from farm import run_aura

    plant_id = spec["id"]
    name, arity = meta["name"], meta["arity"]
    raw_grid = cfg.get("grid2") if arity == 2 else cfg.get("grid", [-3, -1, 0, 1, 2])
    raw_expect = ((cfg.get("plants") or {}).get(plant_id) or {}).get("expect")
    grid, expect = aura_safe_grid(raw_grid, raw_expect, arity)
    send = [p for p in props if not p.get("gate")]
    traj_cut = "depth"
    fork_rows: list[dict] = []
    measured: list | None = None
    if send:
        driver = emit_controller_hop(spec["source"], name, grid, send, arity)
        try:
            raw = run_aura(driver, timeout=45)
        except PatchError:
            raw = ""
            traj_cut = "aura"
        obs_raw, fork_rows = RO._parse_aura_hop(raw)
        if isinstance(obs_raw, dict) and isinstance(obs_raw.get("vals"), list):
            measured = list(obs_raw["vals"])
        elif traj_cut != "aura":
            traj_cut = "aura"
    if measured is None:
        measured = []
        if send:
            traj_cut = "aura"
    pre = _observe(plant_id, measured, name, expect)
    rewards = []
    sent_i = 0
    for prop in props:
        if prop.get("gate"):
            rewards.append(score_fork(pre, None, prop, cfg, gate=prop["gate"]))
            continue
        if traj_cut == "aura":
            rewards.append(score_fork(pre, None, prop, cfg, gate="rebind"))
            sent_i += 1
            continue
        fr = next((f for f in fork_rows if f.get("i") == sent_i), None)
        sent_i += 1
        gate = _fork_gate(fr)
        if gate:
            rewards.append(score_fork(pre, None, prop, cfg, gate=gate))
            continue
        post_vals = ((fr or {}).get("obs") or {}).get("vals") or []
        post = _observe(plant_id, post_vals if isinstance(post_vals, list) else [], name, expect)
        rewards.append(score_fork(pre, post, prop, cfg))
    obs_out = {k: v for k, v in pre.items() if k != "expect"}
    return _finish(
        plant_id,
        props,
        rewards,
        spec["source"],
        fit_intent(plant_id),
        obs_out,
        "aura",
        proposer,
        float(cfg.get("advantage_min", 0.0)),
        traj_cut,
    )


def catalog_props(spec: dict, rewrites: list[dict], k: int, observe: dict[str, Any]) -> list[dict]:
    props = []
    for prop in RO.propose_arith(spec, rewrites, k):
        props.append(prepare_target(prop["target"], observe))
    return props


def run_plant(
    spec: dict,
    meta: dict,
    cfg: dict,
    rewrites: list[dict],
    targets: list[Any] | None,
    host: str,
    proposer: str,
    k: int,
) -> tuple[list[dict], dict]:
    name = meta["name"]
    sketch = {"hot": [name], "frozen": [], "epoch": 1}
    if targets is None:
        props = catalog_props(spec, rewrites, k, sketch)
    else:
        props = [prepare_target(t, sketch) for t in targets[:k]]
    if not props:
        raise PatchError(f"no patches for {spec['id']}")
    if host == "aura":
        return group_aura(spec, meta, cfg, props, proposer)
    return group_dry(spec, meta, cfg, props, rewrites, proposer)


def export_hops(hops: list[dict], path: Path) -> int:
    from export_sft import drop_reason, to_sft

    kept = []
    for hop in hops:
        if hop.get("kind") != "hop":
            continue
        if drop_reason(hop):
            continue
        kept.append(to_sft(hop))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in kept:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return len(kept)


def _plant(plants: list[dict], plant_id: str) -> dict:
    spec = next((p for p in plants if p["id"] == plant_id), None)
    if spec is None:
        known = ", ".join(p["id"] for p in plants)
        raise PatchError(f"unknown plant {plant_id!r}. Have: {known}")
    if plant_id not in W.ARITH_PLANTS:
        raise PatchError(f"{plant_id} has no closed arith probe")
    return spec


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--project", default=PROJECT)
    ap.add_argument("--plant", default="arith-core.p0")
    ap.add_argument("--host", default="dry-world", choices=("dry-world", "aura"))
    ap.add_argument("--proposer", default="catalog", choices=("catalog", "completions"))
    ap.add_argument("--completions", type=Path, default=None)
    ap.add_argument("--forks", type=int, default=8)
    ap.add_argument("--depth", type=int, default=1)
    ap.add_argument("-o", "--out", type=Path, default=None)
    ap.add_argument("--export", type=Path, default=None)
    args = ap.parse_args(argv)
    if args.project != PROJECT:
        print(
            f"error: controller loop is {PROJECT} depth-1. Other projects stay on scripts/rollout.py.",
            file=sys.stderr,
        )
        return 2
    if args.depth != 1:
        print("error: controller loop is depth-1", file=sys.stderr)
        return 2
    if args.forks < 2:
        print("error: --forks must be >= 2 so the group has a baseline", file=sys.stderr)
        return 2
    if args.proposer == "completions" and args.completions is None:
        print("error: --proposer completions needs --completions FILE", file=sys.stderr)
        return 2
    if args.proposer == "catalog" and args.completions is not None:
        print("error: --completions is only for --proposer completions", file=sys.stderr)
        return 2
    if args.host == "aura":
        from apply import pick_bin

        try:
            pick_bin()
        except SystemExit:
            print("error: --host aura requires an Aura binary (AURA_BIN or ../aura-grok/build/aura)", file=sys.stderr)
            return 2
    cfg = json.loads((ROOT / "catalog" / "rewards" / "arith-core.json").read_text(encoding="utf-8"))
    plants, rewrites = load_project(PROJECT)
    try:
        spec = _plant(plants, args.plant)
        groups: dict[str, list[Any] | None] = {args.plant: None}
        if args.proposer == "completions":
            groups = load_completion_groups(args.completions, args.plant, args.forks)
            for pid in groups:
                _plant(plants, pid)
    except (PatchError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    out_path = args.out or (ROOT / "data" / "raw" / "controller-arith-core.jsonl")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    sft_n = 0
    hops_all: list[dict] = []
    with out_path.open("w", encoding="utf-8") as fh:
        for pid, targets in groups.items():
            spec = _plant(plants, pid)
            try:
                hops, traj = run_plant(
                    spec,
                    W.ARITH_PLANTS[pid],
                    cfg,
                    rewrites,
                    targets,
                    args.host,
                    args.proposer,
                    args.forks,
                )
            except PatchError as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 1
            for hop in hops:
                fh.write(json.dumps(hop, ensure_ascii=False) + "\n")
                n += 1
                if hop.get("sft"):
                    sft_n += 1
            fh.write(json.dumps(traj, ensure_ascii=False) + "\n")
            n += 1
            hops_all.extend(hops)
            if traj.get("cut") == "aura":
                print(f"error: aura group failed for {pid}", file=sys.stderr)
                print(
                    f"CONTROLLER project={PROJECT} plant={pid} host={args.host} "
                    f"lines={n} sft={sft_n} out={out_path}"
                )
                return 1
    exported = None
    if args.export is not None:
        exported = export_hops(hops_all, args.export)
    tail = f" export={exported} export_out={args.export}" if exported is not None else ""
    print(
        f"CONTROLLER project={PROJECT} plant={args.plant} host={args.host} "
        f"proposer={args.proposer} lines={n} sft={sft_n} out={out_path}{tail}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
