import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import reward as R  # noqa: E402
import rollout as RO  # noqa: E402
import sandbox_world as W  # noqa: E402


class RewardTwin(unittest.TestCase):
    def setUp(self):
        self.cfg = json.loads((ROOT / "catalog" / "rewards" / "twin-step.json").read_text())

    def test_energy_drop_positive(self):
        pre = {"t": 0, "energy": 10.0}
        post = {"t": 40, "energy": 4.0}
        rw = R.reward_twin(pre, post, {"kind": "synthesis"}, self.cfg)
        self.assertGreater(rw["r"], 0)
        self.assertEqual(rw["cut"], "")

    def test_t_break_hard(self):
        pre = {"t": 0, "energy": 10.0}
        post = {"t": 0, "energy": 1.0}
        rw = R.reward_twin(pre, post, {"kind": "synthesis"}, self.cfg)
        self.assertLess(rw["r"], 0)
        self.assertEqual(rw["cut"], "t_break")

    def test_refuse_when_worse(self):
        pre = {"t": 0, "energy": 4.0}
        post = {"t": 40, "energy": 9.0}
        good = R.reward_twin(pre, post, {"kind": "refuse"}, self.cfg)
        bad = R.reward_twin(pre, post, {"kind": "synthesis"}, self.cfg)
        self.assertGreater(good["r"], bad["r"])

    def test_sign_damp_sat_penalty(self):
        w0 = dict(W.PLANTS["sat-plant"]["world0"])
        pre_w = W.run_twin("sat-plant", "zero-u", 8, w0)
        post_w = W.run_twin("sat-plant", "sign-damp", 40, pre_w)
        pre = W.observe_twin("sat-plant", pre_w, 1)
        post = W.observe_twin("sat-plant", post_w, 1)
        rw = R.reward_twin(pre, post, {"kind": "synthesis"}, self.cfg)
        self.assertIn("sat", rw["components"])


class RewardSession(unittest.TestCase):
    def setUp(self):
        self.cfg = json.loads((ROOT / "catalog" / "rewards" / "session-hot.json").read_text())

    def test_kill_alive_breaks(self):
        s0 = {"id": 1, "fd": 7, "alive": True, "seq": 0}
        s1 = W.run_session("kill-alive", 8, s0)
        pre = W.observe_session(s0, 1)
        post = W.observe_session(s1, 1)
        rw = R.reward_session(pre, post, {"kind": "synthesis"}, self.cfg, 8)
        self.assertEqual(rw["cut"], "identity")
        self.assertLess(rw["r"], 0)

    def test_clip_holds_identity(self):
        s0 = {"id": 1, "fd": 7, "alive": True, "seq": 0}
        s1 = W.run_session("clip-abs", 8, s0)
        pre = W.observe_session(s0, 1)
        post = W.observe_session(s1, 1)
        rw = R.reward_session(pre, post, {"kind": "synthesis"}, self.cfg, 8)
        self.assertNotEqual(rw["cut"], "identity")
        self.assertGreater(rw["r"], 0)


class Tree(unittest.TestCase):
    def test_sandbox_aura_has_no_fiber_spawn(self):
        text = (ROOT / "lib" / "sandbox.aura").read_text(encoding="utf-8")
        self.assertNotIn("fiber:spawn", text)
        self.assertNotIn("fiber:", text)
        src = RO.emit_aura_twin_hop(
            "(define step (lambda (w u) w))\n(define energy (lambda (w) 0))\n(define control (lambda (w) 0))",
            '(hash "x" 2 "v" 1 "t" 0)',
            40,
            40,
            [{"kind": "synthesis", "target": RO._patch("control", "(lambda (world) 0)", "zero-u")}],
            1,
        )
        self.assertNotIn("fiber:spawn", src)
        self.assertIn("ast:snapshot", src)
        self.assertIn("EDSL_OBS", src)

    def test_host_aura_without_bin_exits_2(self):
        from unittest.mock import patch

        with patch.object(RO, "pick_bin", side_effect=SystemExit("no aura")):
            rc = RO.main(["--host", "aura", "-o", str(ROOT / "data" / "raw" / "nope.jsonl")])
        self.assertEqual(rc, 2)

    def test_unknown_summary_dropped(self):
        mapped = RO.map_catalog_proposals(
            [
                {"summary": "pd", "name": "control"},
                {"summary": "not-in-catalog", "name": "control"},
                {"summary": "clip-u", "name": "control"},
            ]
        )
        self.assertEqual([m["summary"] for m in mapped], ["pd", "clip-u"])
        self.assertTrue(all(m.get("proposer") == "agent:ask" for m in mapped))

    def test_teacher_and_rollout_workers_are_mutate_free(self):
        import re

        for rel in ("lib/teacher.aura", "lib/rollout-workers.aura"):
            text = (ROOT / rel).read_text(encoding="utf-8")
            code = re.sub(r";[^\n]*", "", text)
            self.assertNotIn("set-code", code, rel)
            self.assertNotIn("mutate:rebind", code, rel)
            self.assertNotIn("eval-current", code, rel)

    def test_twin_emits_hops_and_traj(self):
        cfg = json.loads((ROOT / "catalog" / "rewards" / "twin-step.json").read_text())
        hops, traj = RO.rollout_twin(cfg, depth=3, forks=4, plant="mass-spring")
        self.assertGreaterEqual(len(hops), 3)
        self.assertEqual(traj["kind"], "traj")
        self.assertTrue(any(h.get("sft") for h in hops) or traj["cut"])
        self.assertTrue(all("observe" in h["input"] for h in hops))

    def test_session_does_not_continue_after_kill_as_best_if_cut(self):
        cfg = json.loads((ROOT / "catalog" / "rewards" / "session-hot.json").read_text())
        hops, traj = RO.rollout_session(cfg, depth=4, forks=4)
        self.assertTrue(hops)
        kills = [h for h in hops if h["id"].endswith("kill-alive")]
        for h in kills:
            self.assertFalse(h.get("sft"))


def _aura_available() -> bool:
    try:
        from apply import pick_bin

        pick_bin()
        return True
    except SystemExit:
        return False


@unittest.skipUnless(_aura_available(), "Aura binary not found")
class AuraHost(unittest.TestCase):
    def test_twin_smoke_observe_t_steps(self):
        cfg = json.loads((ROOT / "catalog" / "rewards" / "twin-step.json").read_text())
        hops, traj = RO.rollout_twin_aura(cfg, depth=1, forks=2, plant="mass-spring")
        self.assertTrue(hops)
        self.assertEqual(traj.get("host"), "aura")
        obs_t = hops[0]["input"]["observe"]["t"]
        self.assertEqual(obs_t, cfg.get("n_pre", 40))
        blob = json.dumps(hops)
        self.assertNotIn("fiber:spawn", blob)
        self.assertNotIn('"restore"', blob)
        self.assertNotIn('"skip"', blob)

    def test_agent_ask_proposer_smoke(self):
        cfg = json.loads((ROOT / "catalog" / "rewards" / "twin-step.json").read_text())
        cfg = dict(cfg)
        cfg["proposers"] = "agent-ask"
        hops, traj = RO.rollout_twin_aura(cfg, depth=1, forks=2, plant="mass-spring")
        self.assertTrue(hops)
        self.assertTrue(any(h.get("proposer") == "agent:ask" for h in hops))
        self.assertTrue(all(h["target"][-1].get("summary") != "not-in-catalog" for h in hops))


if __name__ == "__main__":
    unittest.main()
