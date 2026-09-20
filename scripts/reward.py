"""Dense rewards for forked rollouts. Host-side; no LLM."""
from __future__ import annotations

from typing import Any


def _w(cfg: dict[str, Any], key: str, default: float) -> float:
    return float(cfg.get("weights", {}).get(key, default))


def reward_twin(pre: dict[str, Any], post: dict[str, Any], action: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    comp: dict[str, float] = {}
    r = 0.0
    n_post = int(cfg.get("n_post", 40))
    t0, t1 = float(pre.get("t", 0)), float(post.get("t", 0))
    if t1 != t0 + n_post:
        comp["t_mono"] = _w(cfg, "t_break", -10.0)
        return {"r": comp["t_mono"], "components": comp, "cut": "t_break"}
    comp["t_mono"] = 0.2
    r += 0.2

    e0 = float(pre.get("energy", 0))
    e1 = float(post.get("energy", 0))
    eps = float(cfg.get("energy_eps", 1.0))
    de = (e0 - e1) / max(e0, eps)
    if de > 1:
        de = 1.0
    if de < -1:
        de = -1.0
    comp["energy"] = _w(cfg, "energy", 5.0) * de
    r += comp["energy"]

    sat0, sat1 = float(pre.get("sat", 0)), float(post.get("sat", 0))
    cap = float(cfg.get("sat_cap_frac", 0.5)) * n_post
    if sat1 - sat0 > cap:
        comp["sat"] = _w(cfg, "sat_over", -3.0)
        r += comp["sat"]
    else:
        comp["sat"] = 0.0

    kind = action.get("kind")
    if kind == "refuse" and e1 >= e0:
        comp["contract"] = _w(cfg, "refuse_correct", 2.0)
        r += comp["contract"]
    elif kind == "synthesis" and e1 >= e0:
        comp["contract"] = _w(cfg, "rebind_worse", -2.0)
        r += comp["contract"]
    else:
        comp["contract"] = 0.0

    cut = ""
    if kind == "synthesis" and e1 >= e0:
        cut = "reward"
    return {"r": r, "components": comp, "cut": cut}


def reward_session(pre: dict[str, Any], post: dict[str, Any], action: dict[str, Any], cfg: dict[str, Any], k: int) -> dict[str, Any]:
    a0 = pre.get("session") or {}
    a1 = post.get("session") or {}
    comp: dict[str, float] = {}
    r = 0.0
    cut = ""
    if a1.get("alive") is False or a1.get("id") != a0.get("id") or a1.get("fd") != a0.get("fd"):
        comp["identity"] = _w(cfg, "identity_break", -20.0)
        return {"r": comp["identity"], "components": comp, "cut": "identity"}
    comp["identity"] = _w(cfg, "identity_ok", 1.0)
    r += comp["identity"]
    dseq = int(a1.get("seq", 0)) - int(a0.get("seq", 0))
    if dseq not in (0, k):
        comp["seq"] = _w(cfg, "seq_jump", -5.0)
        r += comp["seq"]
        cut = "seq"
    else:
        comp["seq"] = 0.0
    kind = action.get("kind")
    if kind == "refuse" and cut:
        comp["contract"] = _w(cfg, "refuse_correct", 2.0)
        r += comp["contract"]
    elif kind == "synthesis" and cut:
        comp["contract"] = _w(cfg, "rebind_worse", -2.0)
        r += comp["contract"]
    else:
        comp["contract"] = 0.0
    return {"r": r, "components": comp, "cut": cut}
