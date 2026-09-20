"""In-process worlds for rollout.py --dry-world.

Mirrors the twin-step / session-hot *contracts*, not Aura eval.
Aura host path (--host aura) must reproduce the same observe keys.
"""
from __future__ import annotations

import copy
from typing import Any, Callable


World = dict[str, Any]
Control = Callable[[World], float]
Tick = Callable[[World, World], tuple[float, World]]


def energy_mass(w: World) -> float:
    return float(w.get("x", 0) ** 2 + w.get("v", 0) ** 2)


def energy_two(w: World) -> float:
    return float(
        w.get("x1", 0) ** 2
        + w.get("v1", 0) ** 2
        + w.get("x2", 0) ** 2
        + w.get("v2", 0) ** 2
    )


def step_mass(w: World, u: float) -> World:
    n = dict(w)
    n["x"] = n.get("x", 0) + n.get("v", 0)
    n["v"] = n.get("v", 0) + u
    n["t"] = n.get("t", 0) + 1
    return n


def step_sat(w: World, u: float) -> World:
    n = dict(w)
    clipped = max(-1.0, min(1.0, u))
    n["sat"] = n.get("sat", 0) + (1 if clipped != u else 0)
    n["x"] = n.get("x", 0) + n.get("v", 0)
    n["v"] = n.get("v", 0) + clipped
    n["t"] = n.get("t", 0) + 1
    return n


def step_push(w: World, u: float) -> World:
    n = step_mass(w, u)
    if n["t"] % 10 == 0:
        n["v"] = n.get("v", 0) + 2.0
    return n


def step_two(w: World, u: float) -> World:
    n = dict(w)
    k = 0.2
    x1, v1 = n.get("x1", 0), n.get("v1", 0)
    x2, v2 = n.get("x2", 1), n.get("v2", 0)
    force = -k * (x1 - x2)
    n["x1"] = x1 + v1
    n["v1"] = v1 + u + force
    n["x2"] = x2 + v2
    n["v2"] = v2 - force
    n["t"] = n.get("t", 0) + 1
    return n


PLANTS: dict[str, dict[str, Any]] = {
    "mass-spring": {
        "step": step_mass,
        "energy": energy_mass,
        "world0": {"x": 2.0, "v": 1.0, "t": 0},
        "hot": ["control"],
        "frozen": ["step", "energy"],
    },
    "sat-plant": {
        "step": step_sat,
        "energy": energy_mass,
        "world0": {"x": 2.0, "v": 1.0, "t": 0, "sat": 0},
        "hot": ["control"],
        "frozen": ["step", "energy"],
    },
    "push-obs": {
        "step": step_push,
        "energy": energy_mass,
        "world0": {"x": 2.0, "v": 1.0, "t": 0},
        "hot": ["control"],
        "frozen": ["step", "energy"],
    },
    "two-mass": {
        "step": step_two,
        "energy": energy_two,
        "world0": {"x1": 2.0, "v1": 1.0, "x2": -1.0, "v2": 0.0, "t": 0},
        "hot": ["control"],
        "frozen": ["step", "energy"],
    },
}


CONTROLS: dict[str, Control] = {
    "zero-u": lambda w: 0.0,
    "hold": lambda w: 0.0,
    "damp-v": lambda w: -float(w.get("v", w.get("v1", 0))),
    "p-x": lambda w: -float(w.get("x", w.get("x1", 0))),
    "pd": lambda w: -float(w.get("x", w.get("x1", 0))) - float(w.get("v", w.get("v1", 0))),
    "clip-u": lambda w: max(-1.0, min(1.0, -float(w.get("x", 0)) - float(w.get("v", 0)))),
    "sign-damp": lambda w: 1.0 if float(w.get("v", 0)) < 0 else -1.0,
}


def run_twin(plant_id: str, control_id: str, n: int, world: World | None = None) -> World:
    spec = PLANTS[plant_id]
    step = spec["step"]
    ctrl = CONTROLS[control_id]
    w = copy.deepcopy(world if world is not None else spec["world0"])
    for _ in range(n):
        w = step(w, float(ctrl(w)))
    return w


def observe_twin(plant_id: str, w: World, epoch: int) -> dict[str, Any]:
    spec = PLANTS[plant_id]
    obs: dict[str, Any] = {
        "t": w.get("t", 0),
        "energy": spec["energy"](w),
        "hot": list(spec["hot"]),
        "frozen": list(spec["frozen"]),
        "epoch": epoch,
        "plant": plant_id,
    }
    if "sat" in w:
        obs["sat"] = w["sat"]
    return obs


def tick_hold(book: World, sess: World) -> tuple[float, World]:
    s = dict(sess)
    s["seq"] = s.get("seq", 0) + 1
    q = 0.0
    if "mid" in book:
        q = float(book["mid"])
        if q > 2:
            q = 2.0
        if q < -2:
            q = -2.0
    return q, s


def tick_kill(book: World, sess: World) -> tuple[float, World]:
    s = dict(sess)
    s["alive"] = False
    return 0.0, s


def tick_jump(book: World, sess: World) -> tuple[float, World]:
    s = dict(sess)
    s["seq"] = s.get("seq", 0) + 5
    return 9.0, s


TICKS: dict[str, Tick] = {
    "clip-abs": tick_hold,
    "flat-zero": lambda b, s: (0.0, {**s, "seq": s.get("seq", 0) + 1}),
    "kill-alive": tick_kill,
    "jump-seq": tick_jump,
}


def run_session(tick_id: str, k: int, sess: World | None = None, book: World | None = None) -> World:
    s = copy.deepcopy(sess or {"id": 1, "fd": 7, "alive": True, "seq": 0})
    b = book or {"mid": 3.0, "bid": 1.0, "ask": 5.0}
    fn = TICKS[tick_id]
    for _ in range(k):
        _, s = fn(b, s)
    return s


def observe_session(sess: World, epoch: int) -> dict[str, Any]:
    return {
        "session": {
            "id": sess.get("id"),
            "fd": sess.get("fd"),
            "alive": sess.get("alive"),
            "seq": sess.get("seq", 0),
        },
        "hot": ["tick"],
        "frozen": ["*session*", "gate"],
        "epoch": epoch,
    }
