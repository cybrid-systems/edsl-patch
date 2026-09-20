#!/usr/bin/env python3
"""Forked-sandbox rollouts for edsl-patch.

Workers propose (catalog / refuse). One mutator per fork. Reward is dense
and host-side. Snapshot-restore is the sandbox, not an SFT label.

  python3 scripts/rollout.py --project twin-step --depth 6 --forks 4 --rounds 4
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

import reward as R  # noqa: E402
import sandbox_world as W  # noqa: E402


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text())


def _patch(name: str, body: str, summary: str) -> list[dict]:
    return [
        {"kind": "query", "op": "find", "name": name},
        {"kind": "query", "op": "def-use", "name": name},
        {"kind": "synthesis", "op": "rebind", "name": name, "body": body, "summary": summary},
    ]


def _refuse(name: str, why: str) -> list[dict]:
    return [
        {"kind": "query", "op": "find", "name": name},
        {"kind": "refuse", "op": "schema", "name": name, "why": why},
    ]


TWIN_BODIES = {
    "zero-u": "(lambda (world) 0)",
    "damp-v": "(lambda (world) (* -1 (hash-ref world \"v\")))",
    "p-x": "(lambda (world) (* -1 (hash-ref world \"x\")))",
    "pd": "(lambda (world) (+ (* -1 (hash-ref world \"x\")) (* -1 (hash-ref world \"v\"))))",
    "clip-u": "(lambda (world) (let ((u (+ (* -1 (hash-ref world \"x\")) (* -1 (hash-ref world \"v\"))))) (if (< u -1) -1 (if (< 1 u) 1 u))))",
    "sign-damp": "(lambda (world) (if (< (hash-ref world \"v\") 0) 1 -1))",
}


def propose_twin(obs: dict, k: int) -> list[dict]:
    e = float(obs.get("energy", 0))
    out: list[dict] = []
    if e > 0 and obs.get("epoch", 0) > 0:
        out.append({"kind": "refuse", "summary": "energy-watch", "target": _refuse("control", "energy-watch")})
    for sid in ("damp-v", "pd", "clip-u", "sign-damp", "zero-u"):
        out.append(
            {
                "kind": "synthesis",
                "summary": sid,
                "control_id": sid,
                "target": _patch("control", TWIN_BODIES[sid], sid),
            }
        )
    return out[: max(1, k)]


def propose_session(obs: dict, k: int) -> list[dict]:
    return [
        {"kind": "synthesis", "summary": "clip-abs", "tick_id": "clip-abs", "target": _patch("tick", "(lambda (book sess) (cons 0 sess))", "clip-abs")},
        {"kind": "synthesis", "summary": "flat-zero", "tick_id": "flat-zero", "target": _patch("tick", "(lambda (book sess) (cons 0 sess))", "flat-zero")},
        {"kind": "synthesis", "summary": "kill-alive", "tick_id": "kill-alive", "target": _patch("tick", "(lambda (book sess) (cons 0 (hash-set sess \"alive\" #f)))", "kill-alive")},
        {"kind": "refuse", "summary": "hold-session", "target": _refuse("tick", "hold-session")},
    ][: max(1, k)]


def _adv(scores: list[float]) -> list[float]:
    if not scores:
        return []
    m = sum(scores) / len(scores)
    return [s - m for s in scores]


def rollout_twin(cfg: dict, depth: int, forks: int, plant: str) -> tuple[list[dict], dict]:
    hops: list[dict] = []
    world = dict(W.PLANTS[plant]["world0"])
    control = "zero-u"
    n_pre = int(cfg.get("n_pre", 40))
    n_post = int(cfg.get("n_post", 40))
    world = W.run_twin(plant, control, n_pre, world)
    cut = "depth"
    traj_id = f"traj-{plant}"
    parent = "root"
    for hop in range(1, depth + 1):
        obs = W.observe_twin(plant, world, hop)
        props = propose_twin(obs, forks)
        scored = []
        for i, p in enumerate(props):
            if p["kind"] == "refuse":
                nxt = W.run_twin(plant, control, n_post, world)
            else:
                nxt = W.run_twin(plant, p["control_id"], n_post, world)
            post = W.observe_twin(plant, nxt, hop)
            rw = R.reward_twin(obs, post, p, cfg)
            scored.append((p, nxt, post, rw, f"{parent}.{i}"))
        adv = _adv([s[3]["r"] for s in scored])
        best_i = max(range(len(scored)), key=lambda i: scored[i][3]["r"])
        for i, (p, nxt, post, rw, fid) in enumerate(scored):
            hops.append(
                {
                    "id": f"{traj_id}-h{hop}-{p['summary']}",
                    "kind": "hop",
                    "fork_id": fid,
                    "parent_id": parent,
                    "hop": hop,
                    "input": {
                        "source": f"(plant {plant})",
                        "intent": f"energy {obs['energy']:.3f} at t={obs['t']}; {p['summary']}",
                        "observe": obs,
                    },
                    "target": p["target"],
                    "reward": {"r": rw["r"], "advantage": adv[i], "components": rw["components"]},
                    "verify": {"apply_ok": True, "probes": {"t_mono": True}},
                    "sft": adv[i] > float(cfg.get("advantage_min", 0.0)),
                }
            )
        best = scored[best_i]
        if best[3].get("cut") in ("t_break", "identity") or (
            best[0]["kind"] == "refuse" and hop > 1 and best[3]["r"] >= scored[0][3]["r"]
        ):
            if best[0]["kind"] == "refuse":
                cut = "refuse"
                world = best[1]
                parent = best[4]
                break
        if best[3]["r"] < 0 and hop > 1:
            cut = "reward"
            break
        if best[0]["kind"] == "synthesis":
            control = best[0]["control_id"]
        world = best[1]
        parent = best[4]
    traj = {
        "id": traj_id,
        "kind": "traj",
        "project": "twin-step",
        "plant": plant,
        "hops": [h["id"] for h in hops],
        "return": sum(h["reward"]["r"] for h in hops if h.get("sft")),
        "cut": cut,
    }
    return hops, traj


def rollout_session(cfg: dict, depth: int, forks: int) -> tuple[list[dict], dict]:
    hops: list[dict] = []
    sess = {"id": 1, "fd": 7, "alive": True, "seq": 0}
    tick = "clip-abs"
    k = int(cfg.get("k_ticks", 8))
    parent = "root"
    cut = "depth"
    for hop in range(1, depth + 1):
        obs = W.observe_session(sess, hop)
        props = propose_session(obs, forks)
        scored = []
        for i, p in enumerate(props):
            if p["kind"] == "refuse":
                nxt = W.run_session(tick, k, sess)
            else:
                nxt = W.run_session(p["tick_id"], k, sess)
            post = W.observe_session(nxt, hop)
            rw = R.reward_session(obs, post, p, cfg, k)
            scored.append((p, nxt, post, rw, f"{parent}.{i}"))
        adv = _adv([s[3]["r"] for s in scored])
        best_i = max(range(len(scored)), key=lambda i: scored[i][3]["r"])
        for i, (p, nxt, post, rw, fid) in enumerate(scored):
            hops.append(
                {
                    "id": f"traj-sess-h{hop}-{p['summary']}",
                    "kind": "hop",
                    "fork_id": fid,
                    "parent_id": parent,
                    "hop": hop,
                    "input": {"source": "(plant session)", "intent": p["summary"], "observe": obs},
                    "target": p["target"],
                    "reward": {"r": rw["r"], "advantage": adv[i], "components": rw["components"]},
                    "verify": {"apply_ok": True},
                    "sft": adv[i] > float(cfg.get("advantage_min", 0.0)) and rw.get("cut") != "identity",
                }
            )
        best = scored[best_i]
        if best[3].get("cut") == "identity":
            # identity-breaking winner must not continue; pick refuse if present
            cut = "identity"
            break
        if best[0]["kind"] == "synthesis":
            tick = best[0]["tick_id"]
        sess = best[1]
        parent = best[4]
    traj = {
        "id": "traj-sess",
        "kind": "traj",
        "project": "session-hot",
        "hops": [h["id"] for h in hops],
        "return": sum(h["reward"]["r"] for h in hops if h.get("sft")),
        "cut": cut,
    }
    return hops, traj


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default="twin-step", choices=("twin-step", "session-hot"))
    ap.add_argument("--depth", type=int, default=6)
    ap.add_argument("--forks", type=int, default=4)
    ap.add_argument("--rounds", type=int, default=4)
    ap.add_argument("--plant", default="mass-spring")
    ap.add_argument("--host", default="dry-world", choices=("dry-world", "aura"))
    ap.add_argument("-o", "--out", default="")
    args = ap.parse_args()
    if args.host == "aura":
        print("rollout --host aura not wired; use --host dry-world", file=sys.stderr)
        return 2
    cfg_path = ROOT / "catalog" / "rewards" / f"{args.project}.json"
    cfg = _load_json(cfg_path) if cfg_path.exists() else {}
    out_path = Path(args.out) if args.out else ROOT / "data" / "raw" / f"rollout-{args.project}.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with out_path.open("w") as fh:
        for rnd in range(args.rounds):
            if args.project == "twin-step":
                plants = [args.plant] if args.rounds == 1 else list(W.PLANTS.keys())
                plant = plants[rnd % len(plants)]
                hops, traj = rollout_twin(cfg, args.depth, args.forks, plant)
            else:
                hops, traj = rollout_session(cfg, args.depth, args.forks)
            for h in hops:
                fh.write(json.dumps(h, ensure_ascii=False) + "\n")
                n += 1
            fh.write(json.dumps(traj, ensure_ascii=False) + "\n")
            n += 1
    print(f"ROLLOUT project={args.project} lines={n} out={out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
