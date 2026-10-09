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


class RewardArith(unittest.TestCase):
    def setUp(self):
        self.cfg = json.loads((ROOT / "catalog" / "rewards" / "arith-core.json").read_text())

    def test_abs_matches_p0_expect(self):
        pre = {"vals": [-3, -1, 0, 1, 2], "plant": "arith-core.p0"}
        post = {"vals": [3, 1, 0, 1, 2], "plant": "arith-core.p0", "ok": True}
        rw = R.reward_arith(pre, post, {"kind": "synthesis"}, self.cfg)
        self.assertGreater(rw["r"], 4.0)
        self.assertEqual(rw["cut"], "")

    def test_eval_fail_hard(self):
        pre = {"vals": [0], "plant": "arith-core.p0"}
        post = {"vals": [None], "plant": "arith-core.p0", "ok": False}
        rw = R.reward_arith(pre, post, {"kind": "synthesis"}, self.cfg)
        self.assertEqual(rw["cut"], "eval_fail")
        self.assertLess(rw["r"], 0)


class RewardKv(unittest.TestCase):
    def setUp(self):
        self.cfg = json.loads((ROOT / "catalog" / "rewards" / "kv-mini.json").read_text())

    def test_get_eq_beats_miss(self):
        pre = {"vals": [False, False], "plant": "kv-mini.p0"}
        hit = {"vals": [10, False], "plant": "kv-mini.p0", "ok": True, "expect": [10, False]}
        miss = {"vals": [False, False], "plant": "kv-mini.p0", "ok": True, "expect": [10, False]}
        good = R.reward_kv(pre, hit, {"kind": "synthesis"}, self.cfg)
        bad = R.reward_kv(pre, miss, {"kind": "synthesis"}, self.cfg)
        self.assertGreater(good["r"], bad["r"])
        self.assertEqual(good["cut"], "")

    def test_put_cons_heads_box(self):
        pre = {"vals": [0, 0], "plant": "kv-mini.p1"}
        post = {"vals": [1, 1], "plant": "kv-mini.p1", "ok": True, "expect": [1, 1]}
        rw = R.reward_kv(pre, post, {"kind": "synthesis"}, self.cfg)
        self.assertGreater(rw["r"], 4.0)

    def test_false_is_not_eval_fail(self):
        post = {"vals": [False, True], "plant": "kv-mini.p2", "ok": True, "expect": [False, True]}
        rw = R.reward_kv({}, post, {"kind": "synthesis"}, self.cfg)
        self.assertNotEqual(rw["cut"], "eval_fail")
        self.assertEqual(rw["cut"], "")


class RewardFp(unittest.TestCase):
    def setUp(self):
        self.cfg = json.loads((ROOT / "catalog" / "rewards" / "list-fp.json").read_text())

    def test_len_one_beats_empty(self):
        pre = {"vals": [0, 1], "plant": "list-fp.p0"}
        good = {"vals": [0, 1], "plant": "list-fp.p0", "ok": True, "expect": [0, 1]}
        bad = {"vals": [0, 0], "plant": "list-fp.p0", "ok": True, "expect": [0, 1]}
        self.assertGreater(
            R.reward_kv(pre, good, {"kind": "synthesis"}, self.cfg)["r"],
            R.reward_kv(pre, bad, {"kind": "synthesis"}, self.cfg)["r"],
        )

    def test_wrap_cons_one(self):
        post = {"vals": [1, 7], "plant": "list-fp.p3", "ok": True, "expect": [1, 7]}
        rw = R.reward_kv({}, post, {"kind": "synthesis"}, self.cfg)
        self.assertGreater(rw["r"], 4.0)
        self.assertEqual(rw["cut"], "")


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

    def test_reward_projects_discovered(self):
        ids = RO.list_reward_projects()
        self.assertIn("twin-step", ids)
        self.assertIn("session-hot", ids)
        self.assertIn("arith-core", ids)
        self.assertIn("kv-mini", ids)
        self.assertIn("list-fp", ids)
        self.assertIn("siblings", ids)

    def test_unknown_project_exits_2(self):
        rc = RO.main(["--project", "no-such", "-o", str(ROOT / "data" / "raw" / "nope.jsonl")])
        self.assertEqual(rc, 2)

    def test_session_aura_driver_ticks(self):
        src = RO.emit_aura_session_hop(
            '(define *session* (hash "id" 1 "fd" 7 "alive" #t "seq" 0))\n(define tick (lambda (book sess) (hash "q" 0 "sess" sess)))',
            None,
            8,
            [{"kind": "synthesis", "target": RO._patch("tick", "(lambda (book sess) (hash \"q\" 0 \"sess\" sess))", "flat-zero")}],
            1,
        )
        self.assertIn("sandbox:tick-n", src)
        self.assertIn("ast:snapshot", src)
        self.assertNotIn("fiber:spawn", src)

    def test_arith_dry_world_p0_prefers_abs(self):
        cfg = json.loads((ROOT / "catalog" / "rewards" / "arith-core.json").read_text())
        hops, traj = RO.rollout_arith(cfg, depth=1, forks=6, plant_id="arith-core.p0")
        self.assertTrue(hops)
        self.assertEqual(traj["project"], "arith-core")
        by_sum = {h["target"][-1]["summary"]: h for h in hops if h["target"][-1].get("kind") == "synthesis"}
        if "abs" in by_sum and "plus1" in by_sum:
            self.assertGreater(by_sum["abs"]["reward"]["r"], by_sum["plus1"]["reward"]["r"])

    def test_kv_dry_world_p0_prefers_get_eq(self):
        cfg = json.loads((ROOT / "catalog" / "rewards" / "kv-mini.json").read_text())
        hops, traj = RO.rollout_kv(cfg, depth=1, forks=6, plant_id="kv-mini.p0")
        self.assertTrue(hops)
        self.assertEqual(traj["project"], "kv-mini")
        by_sum = {
            h["target"][-1]["summary"]: h
            for h in hops
            if h["target"][-1].get("kind") == "synthesis"
        }
        if "get-eq" in by_sum and "get-first" in by_sum:
            self.assertGreater(by_sum["get-eq"]["reward"]["r"], by_sum["get-first"]["reward"]["r"])
        if "get-eq" in by_sum:
            self.assertGreater(by_sum["get-eq"]["reward"]["r"], 4.0)

    def test_kv_put_prefers_cons(self):
        cfg = json.loads((ROOT / "catalog" / "rewards" / "kv-mini.json").read_text())
        hops, traj = RO.rollout_kv(cfg, depth=1, forks=4, plant_id="kv-mini.p1")
        self.assertTrue(hops)
        by_sum = {
            h["target"][-1]["summary"]: h
            for h in hops
            if h["target"][-1].get("kind") == "synthesis"
        }
        self.assertIn("put-cons", by_sum)
        self.assertGreater(by_sum["put-cons"]["reward"]["r"], 4.0)

    def test_fp_dry_world_vacuous_len_loses(self):
        cfg = json.loads((ROOT / "catalog" / "rewards" / "list-fp.json").read_text())
        hops, traj = RO.rollout_fp(cfg, depth=1, forks=6, plant_id="list-fp.p0")
        self.assertTrue(hops)
        self.assertEqual(traj["project"], "list-fp")
        def hop_key(h):
            last = h["target"][-1]
            return last.get("summary") or last.get("why")

        by_sum = {hop_key(h): h for h in hops}
        if "len-empty" in by_sum and "hold-fp" in by_sum:
            self.assertGreater(
                by_sum["hold-fp"]["reward"]["r"], by_sum["len-empty"]["reward"]["r"]
            )
        if "len-empty" in by_sum:
            self.assertLess(by_sum["len-empty"]["reward"]["r"], 5.0)

    def test_fp_wrap_cons_empty_loses(self):
        cfg = json.loads((ROOT / "catalog" / "rewards" / "list-fp.json").read_text())
        hops, traj = RO.rollout_fp(cfg, depth=1, forks=4, plant_id="list-fp.p3")
        self.assertTrue(hops)
        by_sum = {h["target"][-1].get("summary"): h for h in hops}
        if "cons-empty" in by_sum:
            self.assertLess(by_sum["cons-empty"]["reward"]["r"], 5.0)

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


class RewardSiblings(unittest.TestCase):
    def test_boolean_match_is_not_eval_fail(self):
        cfg = json.loads((ROOT / "catalog" / "rewards" / "siblings.json").read_text())
        action = {"kind": "synthesis"}
        full = R.reward_siblings(
            {},
            {"vals": [True, False], "ok": True, "expect": [True, False]},
            action,
            cfg,
        )
        half = R.reward_siblings(
            {},
            {"vals": [False, False], "ok": True, "expect": [True, False]},
            action,
            cfg,
        )
        self.assertEqual(full["r"], 5.0)
        self.assertEqual(full["cut"], "")
        self.assertEqual(half["r"], 2.5)
        self.assertNotEqual(half["cut"], "eval_fail")

    def test_driver_counts_only_hash_t_and_names_five_repos(self):
        from edsl_patch import ILLEGAL_HINTS, validate_patch

        src = RO.emit_aura_match_hop(
            "(define even? (lambda (n) #f))",
            "(list (even? 2) (even? 3))",
            [
                {
                    "kind": "synthesis",
                    "summary": "even-real",
                    "target": RO._patch("even?", "(lambda (n) (= (modulo n 2) 0))", "even-real"),
                }
            ],
            1,
        )
        self.assertIn("(set! *rb* (eq? *rb* #t))", src)
        self.assertNotIn("fiber:spawn", src)
        self.assertNotIn("synthesize:define", src)
        repos = [p["repo"] for p in RO.SIBLING_PLANTS]
        self.assertEqual(
            repos,
            ["aura-build", "aura-typeplay", "aura-pad", "aura-redis", "aura-maintainer"],
        )
        cfg = json.loads((ROOT / "catalog" / "rewards" / "siblings.json").read_text())
        self.assertEqual(cfg["kind"], "siblings")
        self.assertEqual(cfg["repos"], repos)
        for plant in RO.SIBLING_PLANTS:
            obs = {"hot": [plant["name"]], "frozen": list(plant["frozen"])}
            summaries = []
            for prop in RO.sibling_proposals(plant):
                validate_patch(prop["target"], observe=obs)
                last = prop["target"][-1]
                summaries.append(last.get("summary") or last.get("why"))
                body = last.get("body") or ""
                low = body.lower()
                for hint in ILLEGAL_HINTS:
                    self.assertNotIn(hint, low)
                    self.assertNotIn(hint, body)
            self.assertTrue(any(str(s).endswith("-real") for s in summaries))
            self.assertIn("hold the planted stub", summaries)

    def test_siblings_dry_world_exits_2(self):
        out = Path(tempfile.mkdtemp()) / "rollout-siblings.jsonl"
        rc = RO.main(["--project", "siblings", "--host", "dry-world", "-o", str(out)])
        self.assertEqual(rc, 2)
        self.assertFalse(out.exists())


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

    def test_session_smoke_observe_identity(self):
        cfg = json.loads((ROOT / "catalog" / "rewards" / "session-hot.json").read_text())
        hops, traj = RO.rollout_session_aura(cfg, depth=1, forks=2, plant="tick-hold")
        self.assertTrue(hops)
        self.assertEqual(traj.get("host"), "aura")
        sess = hops[0]["input"]["observe"]["session"]
        self.assertEqual(sess.get("id"), 1)
        self.assertTrue(sess.get("alive"))
        kills = [h for h in hops if h["id"].endswith("kill-alive")]
        for h in kills:
            self.assertFalse(h.get("sft"))
        blob = json.dumps(hops)
        self.assertNotIn("fiber:spawn", blob)
        self.assertNotIn('"skip"', blob)

    def test_arith_aura_grid(self):
        cfg = json.loads((ROOT / "catalog" / "rewards" / "arith-core.json").read_text())
        hops, traj = RO.rollout_arith_aura(cfg, depth=1, forks=3, plant_id="arith-core.p0")
        self.assertTrue(hops)
        self.assertEqual(traj.get("host"), "aura")
        self.assertIn("vals", hops[0]["input"]["observe"])

    def test_kv_aura_get_lookup(self):
        cfg = json.loads((ROOT / "catalog" / "rewards" / "kv-mini.json").read_text())
        hops, traj = RO.rollout_kv_aura(cfg, depth=1, forks=3, plant_id="kv-mini.p0")
        self.assertTrue(hops)
        self.assertEqual(traj.get("host"), "aura")
        self.assertIn("vals", hops[0]["input"]["observe"])
        by_sum = {
            h["target"][-1]["summary"]: h
            for h in hops
            if h["target"][-1].get("kind") == "synthesis"
        }
        if "get-eq" in by_sum:
            self.assertGreater(by_sum["get-eq"]["reward"]["r"], 0)

    def test_fp_aura_len(self):
        cfg = json.loads((ROOT / "catalog" / "rewards" / "list-fp.json").read_text())
        hops, traj = RO.rollout_fp_aura(cfg, depth=1, forks=3, plant_id="list-fp.p0")
        self.assertTrue(hops)
        self.assertEqual(traj.get("host"), "aura")
        self.assertIn("vals", hops[0]["input"]["observe"])

    def test_siblings_real_body_wins(self):
        cfg = json.loads((ROOT / "catalog" / "rewards" / "siblings.json").read_text())
        groups = RO.rollout_siblings(cfg)
        self.assertEqual([traj["plant"] for _, traj in groups], cfg["repos"])
        for hops, traj in groups:
            self.assertEqual(traj.get("host"), "aura")
            self.assertEqual(traj.get("cut"), "depth")
            self.assertTrue(hops)
            self.assertTrue(all(h["verify"]["apply_ok"] is True for h in hops))
            self.assertTrue(all(h["input"]["intent"].strip() for h in hops))
            blob = json.dumps(hops)
            self.assertNotIn("fiber:spawn", blob)
            real = [h for h in hops if str(h["target"][-1].get("summary", "")).endswith("-real")]
            self.assertEqual(len(real), 1)
            self.assertTrue(real[0]["sft"])
            self.assertGreater(real[0]["reward"]["advantage"], 0)
            others = [h["reward"]["r"] for h in hops if h is not real[0]]
            self.assertGreater(real[0]["reward"]["r"], max(others))
            sft_hops = [h for h in hops if h.get("sft")]
            self.assertEqual(sft_hops, real)


if __name__ == "__main__":
    unittest.main()
