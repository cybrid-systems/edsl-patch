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


def list_reward_projects() -> list[str]:
    d = ROOT / "catalog" / "rewards"
    if not d.is_dir():
        return []
    return sorted(p.stem for p in d.glob("*.json"))


def load_rewrite_map(pid: str, *, include_neg: bool = False) -> dict[str, dict]:
    from catalog import PROJECTS_ROOT, load_project

    _, rws = load_project(pid)
    out = {rw.get("summary"): rw for rw in rws if rw.get("summary")}
    if include_neg:
        neg = PROJECTS_ROOT / pid / "rewrites.neg.jsonl"
        if neg.is_file():
            for line in neg.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                rw = json.loads(line)
                if rw.get("summary"):
                    out[rw["summary"]] = rw
    return out


def map_catalog_proposals(
    raw: list[dict], *, name: str = "control", bodies: dict | None = None
) -> list[dict]:
    """Host maps worker summaries → catalog bodies. Unknown summaries drop."""
    out: list[dict] = []
    if bodies is None:
        bodies = TWIN_BODIES if name == "control" else {}
    for item in raw:
        summary = item.get("summary")
        if summary not in bodies:
            continue
        n = item.get("name") or name
        out.append(
            {
                "kind": "synthesis",
                "summary": summary,
                "control_id": summary,
                "target": _patch(n, bodies[summary], summary),
                "proposer": "agent:ask",
            }
        )
    return out


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
    bodies = load_rewrite_map("session-hot", include_neg=True)
    fallback = '(lambda (book sess) (hash "q" 0 "sess" sess))'
    out: list[dict] = []
    for sid in ("clip-abs", "flat-zero", "kill-alive"):
        rw = bodies.get(sid) or {}
        out.append(
            {
                "kind": "synthesis",
                "summary": sid,
                "tick_id": sid,
                "target": _patch("tick", rw.get("body") or fallback, sid),
            }
        )
    out.append(
        {"kind": "refuse", "summary": "hold-session", "target": _refuse("tick", "hold-session")}
    )
    return out[: max(1, k)]


def propose_arith(plant: dict, rewrites: list[dict], k: int) -> list[dict]:
    from catalog import is_noop, lambda_arity
    from parse_aura import extract_defines

    names = list(plant.get("hot") or plant.get("names") or ["f"])
    name = names[0]
    defs = extract_defines(plant.get("source") or "")
    plant_ar = lambda_arity(defs.get(name) or "")
    out: list[dict] = []
    for rw in rewrites:
        if rw.get("keep") is False:
            continue
        ar = int(rw.get("arity") or lambda_arity(rw.get("body") or "") or 0)
        if plant_ar >= 0 and ar >= 0 and plant_ar != ar:
            continue
        r = dict(rw)
        r["name"] = name
        if is_noop(plant, r, name):
            continue
        out.append(
            {
                "kind": "synthesis",
                "summary": rw.get("summary") or rw.get("id"),
                "control_id": rw.get("summary"),
                "target": _patch(name, rw["body"], rw.get("summary") or "rebind"),
            }
        )
        if len(out) >= max(1, k) - 1:
            break
    out.append(
        {"kind": "refuse", "summary": "hold-arith", "target": _refuse(name, "hold-arith")}
    )
    return out[: max(1, k)]


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


def emit_aura_session_hop(
    source: str,
    sess_form: str | None,
    k: int,
    props: list[dict],
    epoch: int,
) -> str:
    """One hop: snapshot, sibling tick rebinds. Drive (tick book sess)."""
    book = '(hash "bid" 1 "ask" 3 "mid" 2 "spread" 2 "last" 4 "size" 1)'
    sess_init = sess_form or "*session*"
    lines = [
        ";; rollout --host aura session hop",
        '(require "sandbox" all:)',
        f"(set-code {scheme_string(source)})",
        "(eval-current)",
        f"(define *book* {book})",
        f"(define *sess* {sess_init})",
        '(display "EDSL_OBS ")',
        f"(display (json-encode (sandbox:sess-obs *sess* {int(epoch)})))",
        "(newline)",
        '(define *snap* (try (ast:snapshot "rollout") (catch (e) -1)))',
        "(define *rb* #f)",
        "(define *sf* #f)",
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
            f"(set! *sf* (if *rb* (try (sandbox:tick-n *book* *sess* {int(k)}) (catch (e) #f)) #f))",
            "(if *sf*",
            "  (begin",
            '    (display "EDSL_FORK ")',
            f"    (display (json-encode (hash \"i\" *fi* \"ok\" #t \"obs\" (sandbox:sess-obs *sf* {int(epoch)}))))",
            "    (newline))",
            '  (begin (display "EDSL_FORK ") (display (json-encode (hash "i" *fi* "ok" #f))) (newline)))',
        ]
    lines.append("")
    return "\n".join(lines)


def emit_aura_arith_hop(
    source: str,
    name: str,
    grid: list,
    props: list[dict],
    epoch: int,
    arity: int = 1,
) -> str:
    """One hop: snapshot, sibling rebinds, eval hot name on a numeric grid."""
    if arity == 2:
        pairs = " ".join(f"(list {a} {b})" for a, b in grid)
        grid_form = f"(sandbox:grid2 {name} (list {pairs}))"
    else:
        xs = " ".join(str(x) for x in grid)
        grid_form = f"(sandbox:grid1 {name} (list {xs}))"
    lines = [
        ";; rollout --host aura arith hop",
        '(require "sandbox" all:)',
        f"(set-code {scheme_string(source)})",
        "(eval-current)",
        '(display "EDSL_OBS ")',
        f"(display (json-encode (hash \"epoch\" {int(epoch)} \"vals\" {grid_form})))",
        "(newline)",
        '(define *snap* (try (ast:snapshot "rollout") (catch (e) -1)))',
        "(define *rb* #f)",
        "(define *vs* #f)",
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
            f"(set! *vs* (if *rb* (try {grid_form} (catch (e) #f)) #f))",
            "(if *vs*",
            "  (begin",
            '    (display "EDSL_FORK ")',
            f"    (display (json-encode (hash \"i\" *fi* \"ok\" #t \"obs\" (hash \"epoch\" {int(epoch)} \"vals\" *vs*))))",
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
        if cfg.get("proposers") == "agent-ask":
            from farm import run_aura as _run

            ask = "\n".join(
                [
                    '(require "rollout-workers" all:)',
                    '(display "EDSL_PROP ")',
                    "(display (json-encode (rollout-proposer:ask)))",
                    "(newline)",
                ]
            )
            raw_prop = _run(ask, timeout=20)
            parsed: list[dict] = []
            for line in raw_prop.splitlines():
                if line.startswith("EDSL_PROP "):
                    val = json.loads(line[len("EDSL_PROP ") :])
                    parsed = val if isinstance(val, list) else []
            mapped = map_catalog_proposals(parsed)
            if mapped:
                props = mapped[: max(1, forks)]
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
                    "proposer": p.get("proposer") or "catalog",
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


def _session_obs_from_raw(raw: dict, hop: int) -> dict:
    alive = raw.get("alive")
    if alive in ("#t", True, 1, "true"):
        alive = True
    elif alive in ("#f", False, 0, "false"):
        alive = False
    return {
        "session": {
            "id": raw.get("id"),
            "fd": raw.get("fd"),
            "alive": alive,
            "seq": raw.get("seq", 0),
        },
        "hot": ["tick"],
        "frozen": ["*session*", "gate"],
        "epoch": hop,
    }


def rollout_session_aura(
    cfg: dict, depth: int, forks: int, plant: str = "tick-hold"
) -> tuple[list[dict], dict]:
    from catalog import load_project
    from farm import run_aura
    from parse_aura import extract_defines
    from apply import apply_patch

    plants, _ = load_project("session-hot")
    spec = next((p for p in plants if plant in p["id"]), plants[0])
    source = spec["source"]
    frozen = list(spec.get("frozen") or ["*session*", "gate"])
    hot = list(spec.get("hot") or ["tick"])
    tick0 = extract_defines(source).get("tick")
    k = int(cfg.get("k_ticks", 8))
    hops: list[dict] = []
    parent = "root"
    cut = "depth"
    traj_id = f"traj-aura-{spec['id']}"
    sess_form = None
    for hop in range(1, depth + 1):
        props = propose_session({}, forks)
        driver = emit_aura_session_hop(source, sess_form, k, props, hop)
        raw = run_aura(driver, timeout=45)
        if "fiber:spawn" in driver:
            raise RuntimeError("fiber:spawn is not the fork")
        obs_raw, fork_rows = _parse_aura_hop(raw)
        if not obs_raw:
            cut = "aura"
            break
        obs = _session_obs_from_raw(obs_raw, hop)
        scored = []
        for i, p in enumerate(props):
            fr = next((f for f in fork_rows if f.get("i") == i), None)
            if not fr or not fr.get("ok"):
                continue
            post_raw = dict(fr.get("obs") or {})
            post = _session_obs_from_raw(post_raw, hop)
            rw = R.reward_session(obs, post, p, cfg, k)
            scored.append((p, post, rw, f"{parent}.{i}", post_raw))
        if not scored:
            cut = "aura"
            break
        adv = _adv([s[2]["r"] for s in scored])
        best_i = max(range(len(scored)), key=lambda i: scored[i][2]["r"])
        for i, (p, post, rw, fid, post_raw) in enumerate(scored):
            sft = adv[i] > float(cfg.get("advantage_min", 0.0)) and rw.get("cut") != "identity"
            hops.append(
                {
                    "id": f"{traj_id}-h{hop}-{p['summary']}",
                    "kind": "hop",
                    "fork_id": fid,
                    "parent_id": parent,
                    "hop": hop,
                    "input": {
                        "source": source,
                        "intent": f"session id={obs['session'].get('id')} seq={obs['session'].get('seq')}; {p['summary']}",
                        "observe": obs,
                    },
                    "target": p["target"],
                    "reward": {"r": rw["r"], "advantage": adv[i], "components": rw["components"]},
                    "verify": {"apply_ok": True, "unchanged": frozen, "probes": {"session_stable": True}},
                    "sft": sft,
                    "proposer": p.get("proposer") or "catalog",
                    "host": "aura",
                }
            )
        best = scored[best_i]
        if best[2].get("cut") == "identity":
            cut = "identity"
            break
        if best[0]["kind"] == "refuse" and hop > 1:
            cut = "refuse"
            break
        if best[0]["kind"] == "synthesis":
            try:
                res = apply_patch(source, best[0]["target"])
                if res.get("ok") and res.get("source"):
                    new_tick = extract_defines(res["source"]).get("tick")
                    # frozen names *session*/gate must stay; tick is hot
                    source = res["source"]
                    _ = tick0, new_tick, hot
            except Exception:
                cut = "apply"
                break
        nxt_sess = best[4].get("sess")
        if isinstance(nxt_sess, dict):
            sess_form = _world_form(nxt_sess)
        parent = best[3]
    traj = {
        "id": traj_id,
        "kind": "traj",
        "project": "session-hot",
        "plant": spec["id"],
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


def _arith_expect(cfg: dict, plant_id: str) -> list | None:
    return ((cfg.get("plants") or {}).get(plant_id) or {}).get("expect")


def rollout_arith(cfg: dict, depth: int, forks: int, plant_id: str) -> tuple[list[dict], dict]:
    from catalog import load_project

    plants, rewrites = load_project("arith-core")
    spec = next((p for p in plants if p["id"] == plant_id or plant_id in p["id"]), plants[0])
    plant_id = spec["id"]
    meta = W.ARITH_PLANTS.get(plant_id)
    if not meta:
        return [], {"id": f"traj-{plant_id}", "kind": "traj", "project": "arith-core", "cut": "no-plant", "hops": []}
    name, arity, fn = meta["name"], meta["arity"], meta["fn"]
    grid = cfg.get("grid2") if arity == 2 else cfg.get("grid", [-3, -1, 0, 1, 2])
    hops: list[dict] = []
    parent = "root"
    cut = "depth"
    traj_id = f"traj-{plant_id}"
    current_fn = fn
    current_id = "plant"
    expect = _arith_expect(cfg, plant_id)
    for hop in range(1, depth + 1):
        pre_vals = W.arith_grid_vals(current_fn, grid, arity)
        obs = W.observe_arith(plant_id, pre_vals, hop, name)
        if expect:
            obs["expect"] = expect
        props = propose_arith(spec, rewrites, forks)
        scored = []
        for i, p in enumerate(props):
            if p["kind"] == "refuse":
                nxt_fn = current_fn
            else:
                nxt_fn = W.ARITH_FNS.get(p["summary"])
                if nxt_fn is None:
                    continue
            post_vals = W.arith_grid_vals(nxt_fn, grid, arity)
            post = W.observe_arith(plant_id, post_vals, hop, name)
            if expect:
                post["expect"] = expect
            rw = R.reward_arith(obs, post, p, cfg)
            scored.append((p, nxt_fn, post, rw, f"{parent}.{i}"))
        if not scored:
            cut = "empty"
            break
        adv = _adv([s[3]["r"] for s in scored])
        best_i = max(range(len(scored)), key=lambda i: scored[i][3]["r"])
        for i, (p, nxt_fn, post, rw, fid) in enumerate(scored):
            sft = adv[i] > float(cfg.get("advantage_min", 0.0)) and rw.get("cut") != "eval_fail"
            hops.append(
                {
                    "id": f"{traj_id}-h{hop}-{p['summary']}",
                    "kind": "hop",
                    "fork_id": fid,
                    "parent_id": parent,
                    "hop": hop,
                    "input": {
                        "source": spec["source"],
                        "intent": f"arith grid {grid}; {p['summary']}",
                        "observe": {k: v for k, v in obs.items() if k != "expect"},
                    },
                    "target": p["target"],
                    "reward": {"r": rw["r"], "advantage": adv[i], "components": rw["components"]},
                    "verify": {"apply_ok": True, "probes": {"arith_grid": True}},
                    "sft": sft,
                }
            )
        best = scored[best_i]
        if best[3].get("cut") == "eval_fail":
            cut = "eval_fail"
            break
        if best[0]["kind"] == "refuse" and hop > 1:
            cut = "refuse"
            break
        if best[0]["kind"] == "synthesis":
            current_fn = best[1]
            current_id = best[0]["summary"]
        parent = best[4]
        _ = current_id
    traj = {
        "id": traj_id,
        "kind": "traj",
        "project": "arith-core",
        "plant": plant_id,
        "hops": [h["id"] for h in hops],
        "return": sum(h["reward"]["r"] for h in hops if h.get("sft")),
        "cut": cut,
    }
    return hops, traj


def rollout_arith_aura(cfg: dict, depth: int, forks: int, plant_id: str) -> tuple[list[dict], dict]:
    from catalog import load_project
    from farm import run_aura
    from apply import apply_patch

    plants, rewrites = load_project("arith-core")
    spec = next((p for p in plants if p["id"] == plant_id or plant_id in p["id"]), plants[0])
    plant_id = spec["id"]
    name = (spec.get("hot") or spec.get("names") or ["f"])[0]
    arity = 2 if name == "add" else 1
    grid = cfg.get("grid2") if arity == 2 else cfg.get("grid", [-3, -1, 0, 1, 2])
    expect = _arith_expect(cfg, plant_id)
    source = spec["source"]
    hops: list[dict] = []
    parent = "root"
    cut = "depth"
    traj_id = f"traj-aura-{plant_id}"
    for hop in range(1, depth + 1):
        props = propose_arith(spec, rewrites, forks)
        driver = emit_aura_arith_hop(source, name, grid, props, hop, arity=arity)
        raw = run_aura(driver, timeout=45)
        obs_raw, fork_rows = _parse_aura_hop(raw)
        if not obs_raw:
            cut = "aura"
            break
        obs = {
            "vals": obs_raw.get("vals") or [],
            "ok": True,
            "plant": plant_id,
            "hot": [name],
            "frozen": [],
            "epoch": hop,
        }
        if expect:
            obs["expect"] = expect
        scored = []
        for i, p in enumerate(props):
            fr = next((f for f in fork_rows if f.get("i") == i), None)
            if not fr or not fr.get("ok"):
                continue
            post_raw = fr.get("obs") or {}
            post = {
                "vals": post_raw.get("vals") or [],
                "ok": True,
                "plant": plant_id,
                "hot": [name],
                "frozen": [],
                "epoch": hop,
            }
            if expect:
                post["expect"] = expect
            rw = R.reward_arith(obs, post, p, cfg)
            scored.append((p, post, rw, f"{parent}.{i}"))
        if not scored:
            cut = "aura"
            break
        adv = _adv([s[2]["r"] for s in scored])
        best_i = max(range(len(scored)), key=lambda i: scored[i][2]["r"])
        obs_out = {k: v for k, v in obs.items() if k != "expect"}
        for i, (p, post, rw, fid) in enumerate(scored):
            sft = adv[i] > float(cfg.get("advantage_min", 0.0)) and rw.get("cut") != "eval_fail"
            hops.append(
                {
                    "id": f"{traj_id}-h{hop}-{p['summary']}",
                    "kind": "hop",
                    "fork_id": fid,
                    "parent_id": parent,
                    "hop": hop,
                    "input": {
                        "source": source,
                        "intent": f"arith grid {grid}; {p['summary']}",
                        "observe": obs_out,
                    },
                    "target": p["target"],
                    "reward": {"r": rw["r"], "advantage": adv[i], "components": rw["components"]},
                    "verify": {"apply_ok": True, "probes": {"arith_grid": True}},
                    "sft": sft,
                    "host": "aura",
                }
            )
        best = scored[best_i]
        if best[2].get("cut") == "eval_fail":
            cut = "eval_fail"
            break
        if best[0]["kind"] == "refuse" and hop > 1:
            cut = "refuse"
            break
        if best[0]["kind"] == "synthesis":
            try:
                res = apply_patch(source, best[0]["target"])
                if res.get("ok") and res.get("source"):
                    source = res["source"]
            except Exception:
                cut = "apply"
                break
        parent = best[3]
    traj = {
        "id": traj_id,
        "kind": "traj",
        "project": "arith-core",
        "plant": plant_id,
        "host": "aura",
        "hops": [h["id"] for h in hops],
        "return": sum(h["reward"]["r"] for h in hops if h.get("sft")),
        "cut": cut,
    }
    return hops, traj


def main(argv: list[str] | None = None) -> int:
    known = list_reward_projects()
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--project",
        default="twin-step",
        help="catalog/rewards/<id>.json stem: " + ",".join(known),
    )
    ap.add_argument("--depth", type=int, default=6)
    ap.add_argument("--forks", type=int, default=4)
    ap.add_argument("--rounds", type=int, default=4)
    ap.add_argument("--plant", default="mass-spring")
    ap.add_argument("--host", default="dry-world", choices=("dry-world", "aura"))
    ap.add_argument(
        "--proposers",
        default="catalog",
        choices=("catalog", "agent-ask"),
        help="catalog sampler, or agent:ask workers (host aura only)",
    )
    ap.add_argument("-o", "--out", default="")
    args = ap.parse_args(argv)
    if args.project not in known:
        print(
            f"error: unknown --project {args.project!r}. Add catalog/rewards/<id>.json. "
            f"Have: {', '.join(known) or '(none)'}",
            file=sys.stderr,
        )
        return 2
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
    cfg = _load_json(cfg_path)
    kind = cfg.get("kind") or args.project
    if args.proposers == "agent-ask":
        cfg = dict(cfg)
        cfg["proposers"] = "agent-ask"
    out_path = Path(args.out) if args.out else ROOT / "data" / "raw" / f"rollout-{args.project}.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with out_path.open("w") as fh:
        for rnd in range(args.rounds):
            if kind in ("twin", "twin-step"):
                plants = [args.plant] if args.rounds == 1 else list(W.PLANTS.keys())
                plant = plants[rnd % len(plants)]
                if args.host == "aura":
                    hops, traj = rollout_twin_aura(cfg, args.depth, args.forks, plant)
                else:
                    hops, traj = rollout_twin(cfg, args.depth, args.forks, plant)
            elif kind in ("session", "session-hot"):
                sess_plants = ["tick-hold", "tick-seq", "tick-book-bidask", "tick-gated"]
                plant = args.plant if args.rounds == 1 and "tick" in args.plant else sess_plants[rnd % len(sess_plants)]
                if args.host == "aura":
                    hops, traj = rollout_session_aura(cfg, args.depth, args.forks, plant)
                else:
                    hops, traj = rollout_session(cfg, args.depth, args.forks)
            elif kind == "arith":
                arith_plants = list(W.ARITH_PLANTS.keys())
                plant = args.plant if args.plant in W.ARITH_PLANTS else arith_plants[rnd % len(arith_plants)]
                if args.host == "aura":
                    hops, traj = rollout_arith_aura(cfg, args.depth, args.forks, plant)
                else:
                    hops, traj = rollout_arith(cfg, args.depth, args.forks, plant)
            else:
                print(f"error: reward kind {kind!r} has no rollout handler", file=sys.stderr)
                return 2
            for h in hops:
                fh.write(json.dumps(h, ensure_ascii=False) + "\n")
                n += 1
            fh.write(json.dumps(traj, ensure_ascii=False) + "\n")
            n += 1
    print(f"ROLLOUT project={args.project} kind={kind} host={args.host} lines={n} out={out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
