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
from apply import pick_bin  # noqa: E402
from edsl_patch import scheme_string  # noqa: E402


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
    "sign-damp": "(lambda (world) (if (< (hash-ref world \"v\") 0) 2 -2))",
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


def _world_form(world: dict) -> str:
    parts = []
    for k, v in world.items():
        if isinstance(v, bool):
            parts.append(f'"{k}" {"#t" if v else "#f"}')
        elif isinstance(v, (int, float)):
            parts.append(f'"{k}" {v}')
        else:
            parts.append(f'"{k}" {scheme_string(str(v))}')
    return "(hash " + " ".join(parts) + ")"


def emit_aura_twin_hop(
    source: str,
    world_form: str,
    n_pre: int,
    n_post: int,
    props: list[dict],
    epoch: int,
) -> str:
    """One hop: measure, snapshot, sibling rebinds. No fiber:spawn."""
    lines = [
        ";; rollout --host aura hop (snapshot plumbing, not an SFT restore label)",
        '(require "sandbox" all:)',
        f"(set-code {scheme_string(source)})",
        "(eval-current)",
        f"(define *w0* {world_form})",
        f"(define *w* (sandbox:step-n *w0* {int(n_pre)}))",
        '(display "EDSL_OBS ")',
        f"(display (json-encode (sandbox:obs *w* {int(epoch)})))",
        "(newline)",
        '(define *snap* (try (ast:snapshot "rollout") (catch (e) -1)))',
        "(define *rb* #f)",
        "(define *wf* #f)",
        '(define *metrics* (try (agent:decision-metrics) (catch (e) #f)))',
    ]
    for i, p in enumerate(props):
        lines += [
            f"(define *fi* {i})",
            "(if (and (number? *snap*) (>= *snap* 0)) (try (ast:restore *snap*) (catch (e) #f)) #f)",
            "(try (eval-current) (catch (e) #f))",
        ]
        if p.get("kind") == "synthesis":
            tgt = p["target"][-1]
            lines += [
                f"(set! *rb* (try (mutate:rebind {scheme_string(tgt['name'])} {scheme_string(tgt['body'])} {scheme_string(tgt['summary'])}) (catch (e) #f)))",
                "(if *rb* (try (eval-current) (catch (e) #f)) #f)",
            ]
        else:
            lines += ["(set! *rb* #t)"]
        lines += [
            f"(set! *wf* (if *rb* (try (sandbox:step-n *w* {int(n_post)}) (catch (e) #f)) #f))",
            "(if *wf*",
            "  (begin",
            '    (display "EDSL_FORK ")',
            f"    (display (json-encode (hash \"i\" *fi* \"ok\" #t \"obs\" (sandbox:obs *wf* {int(epoch)}))))",
            "    (newline))",
            '  (begin (display "EDSL_FORK ") (display (json-encode (hash "i" *fi* "ok" #f))) (newline)))',
        ]
    lines.append("")
    return "\n".join(lines)


def _parse_aura_hop(raw: str) -> tuple[dict | None, list[dict]]:
    obs = None
    forks: list[dict] = []
    for line in raw.splitlines():
        if line.startswith("EDSL_OBS "):
            obs = json.loads(line[len("EDSL_OBS ") :])
        elif line.startswith("EDSL_FORK "):
            forks.append(json.loads(line[len("EDSL_FORK ") :]))
    return obs, forks


def rollout_twin_aura(cfg: dict, depth: int, forks: int, plant: str) -> tuple[list[dict], dict]:
    from catalog import load_project
    from farm import run_aura, world_init_aura
    from parse_aura import extract_defines

    plants, _ = load_project("twin-step")
    spec = next((p for p in plants if plant in p["id"]), plants[0])
    source = spec["source"]
    frozen = list(spec.get("frozen") or ["step", "energy"])
    hot = list(spec.get("hot") or ["control"])
    step0 = extract_defines(source).get("step")
    world_form = world_init_aura(spec)
    n_pre = int(cfg.get("n_pre", 40))
    n_post = int(cfg.get("n_post", 40))
    hops: list[dict] = []
    parent = "root"
    cut = "depth"
    traj_id = f"traj-aura-{spec['id']}"
    pre_n = n_pre
    for hop in range(1, depth + 1):
        props = propose_twin({"energy": 50.0, "epoch": hop, "t": 0}, forks)
        driver = emit_aura_twin_hop(source, world_form, pre_n, n_post, props, hop)
        raw = run_aura(driver, timeout=45)
        if "fiber:spawn" in driver:
            raise RuntimeError("fiber:spawn is not the fork")
        obs, fork_rows = _parse_aura_hop(raw)
        if not obs:
            cut = "aura"
            break
        obs = dict(obs)
        world_state = obs.pop("world", None)
        obs["hot"] = hot
        obs["frozen"] = frozen
        obs["plant"] = plant
        obs["epoch"] = hop
        scored = []
        for i, p in enumerate(props):
            fr = next((f for f in fork_rows if f.get("i") == i), None)
            if not fr or not fr.get("ok"):
                continue
            post = dict(fr.get("obs") or {})
            post.pop("world", None)
            post["hot"] = hot
            post["frozen"] = frozen
            post["epoch"] = hop
            rw = R.reward_twin(obs, post, p, cfg)
            scored.append((p, post, rw, f"{parent}.{i}", fr.get("obs") or {}))
        if not scored:
            cut = "aura"
            break
        adv = _adv([s[2]["r"] for s in scored])
        best_i = max(range(len(scored)), key=lambda i: scored[i][2]["r"])
        for i, (p, post, rw, fid, raw_post) in enumerate(scored):
            sft = adv[i] > float(cfg.get("advantage_min", 0.0))
            if rw.get("cut") in ("t_break", "identity", "frozen_break"):
                sft = False
            hops.append(
                {
                    "id": f"{traj_id}-h{hop}-{p['summary']}",
                    "kind": "hop",
                    "fork_id": fid,
                    "parent_id": parent,
                    "hop": hop,
                    "input": {
                        "source": source,
                        "intent": f"energy {obs.get('energy')} at t={obs.get('t')}; {p['summary']}",
                        "observe": obs,
                    },
                    "target": p["target"],
                    "reward": {"r": rw["r"], "advantage": adv[i], "components": rw["components"]},
                    "verify": {
                        "apply_ok": True,
                        "unchanged": frozen,
                        "probes": {"t_mono": True},
                    },
                    "sft": sft,
                }
            )
        best = scored[best_i]
        if best[2].get("cut") in ("t_break", "identity"):
            cut = best[2]["cut"]
            break
        if best[0]["kind"] == "refuse" and hop > 1:
            cut = "refuse"
            break
        if best[2]["r"] < 0 and hop > 1:
            cut = "reward"
            break
        if best[0]["kind"] == "synthesis":
            from apply import apply_patch

            try:
                res = apply_patch(source, best[0]["target"])
                if res.get("ok") and res.get("source"):
                    new_step = extract_defines(res["source"]).get("step")
                    if step0 and new_step and new_step != step0:
                        cut = "frozen"
                        break
                    source = res["source"]
            except Exception:
                cut = "apply"
                break
        nxt_world = best[4].get("world")
        if isinstance(nxt_world, dict):
            world_form = _world_form(nxt_world)
        pre_n = 0
        parent = best[3]
    traj = {
        "id": traj_id,
        "kind": "traj",
        "project": "twin-step",
        "plant": plant,
        "host": "aura",
        "hops": [h["id"] for h in hops],
        "return": sum(h["reward"]["r"] for h in hops if h.get("sft")),
        "cut": cut,
    }
    return hops, traj


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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default="twin-step", choices=("twin-step", "session-hot"))
    ap.add_argument("--depth", type=int, default=6)
    ap.add_argument("--forks", type=int, default=4)
    ap.add_argument("--rounds", type=int, default=4)
    ap.add_argument("--plant", default="mass-spring")
    ap.add_argument("--host", default="dry-world", choices=("dry-world", "aura"))
    ap.add_argument("-o", "--out", default="")
    args = ap.parse_args(argv)
    if args.host == "aura":
        try:
            pick_bin()
        except SystemExit:
            print(
                "error: --host aura requires an Aura binary (AURA_BIN or ../aura-grok/build/aura)",
                file=sys.stderr,
            )
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
                if args.host == "aura":
                    hops, traj = rollout_twin_aura(cfg, args.depth, args.forks, plant)
                else:
                    hops, traj = rollout_twin(cfg, args.depth, args.forks, plant)
            else:
                if args.host == "aura":
                    print("rollout --host aura session-hot uses dry-world this smoke", file=sys.stderr)
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
