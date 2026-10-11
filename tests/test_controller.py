"""Depth-1 arith controller: gates, group advantage, export gold."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import controller as C  # noqa: E402
import rollout as RO  # noqa: E402
from export_sft import drop_reason  # noqa: E402


def _abs_target():
    return RO._patch("f", "(lambda (x) (if (< x 0) (* x -1) x))", "from-model")


def _id_target():
    return RO._patch("f", "(lambda (x) x)", "same")


def _illegal_target():
    return RO._patch("f", "(lambda (x) (fiber:spawn (lambda () x)))", "bad")


class ControllerGates(unittest.TestCase):
    def setUp(self):
        self.cfg = json.loads((ROOT / "catalog" / "rewards" / "arith-core.json").read_text())
        self.pre = {
            "vals": [-3, -1, 0, 1, 2],
            "plant": "arith-core.p0",
            "ok": True,
            "expect": [3, 1, 0, 1, 2],
        }

    def test_schema_and_rebind_and_eval_gates(self):
        schema = C.score_fork(self.pre, None, {"kind": "schema"}, self.cfg, gate="schema")
        rebind = C.score_fork(self.pre, None, {"kind": "synthesis"}, self.cfg, gate="rebind")
        ev = C.score_fork(self.pre, None, {"kind": "synthesis"}, self.cfg, gate="eval")
        self.assertEqual(schema["r"], -20.0)
        self.assertEqual(schema["cut"], "schema")
        self.assertEqual(rebind["r"], -10.0)
        self.assertEqual(ev["r"], -8.0)
        self.assertEqual(ev["cut"], "eval_fail")

    def test_exact_match_beats_identity(self):
        hit = C.score_fork(
            self.pre,
            {"vals": [3, 1, 0, 1, 2], "ok": True, "expect": self.pre["expect"]},
            {"kind": "synthesis"},
            self.cfg,
        )
        same = C.score_fork(
            self.pre,
            {"vals": [-3, -1, 0, 1, 2], "ok": True, "expect": self.pre["expect"]},
            {"kind": "synthesis"},
            self.cfg,
        )
        self.assertEqual(hit["cut"], "")
        self.assertGreater(hit["r"], 4.0)
        self.assertEqual(same["cut"], "identity")
        self.assertEqual(same["r"], 0.0)
        adv = RO._adv([hit["r"], same["r"], -20.0])
        self.assertTrue(C.mark_sft(adv[0], hit, 0.0))
        self.assertFalse(C.mark_sft(adv[1], same, 0.0))

    def test_aura_probe_omits_arguments_the_host_drops(self):
        grid, expect = C.aura_safe_grid([-3, -1, 0, 1, 2], [3, 1, 0, 1, 2], 1)
        self.assertEqual(grid, [-3, 0, 1, 2])
        self.assertEqual(expect, [3, 0, 1, 2])
        pairs, _ = C.aura_safe_grid([[1, -1], [0, 0], [-2, 3]], None, 2)
        self.assertEqual(pairs, [[0, 0]])

    def test_driver_restores_snapshot_and_counts_hash_t(self):
        src = C.emit_controller_hop(
            "(define f (lambda (x) x))",
            "f",
            [-3, -1, 0, 1, 2],
            [{"kind": "synthesis", "summary": "abs", "target": _abs_target()}],
            1,
        )
        self.assertIn('(set! *rb* (eq? *rb* #t))', src)
        self.assertIn('(ast:snapshot "controller")', src)
        self.assertNotIn("fiber:spawn", src)


class ControllerDry(unittest.TestCase):
    def test_catalog_exports_only_exact_match(self):
        out = Path(tempfile.mkdtemp()) / "controller.jsonl"
        export = Path(tempfile.mkdtemp()) / "sft.jsonl"
        rc = C.main(
            [
                "--project",
                "arith-core",
                "--plant",
                "arith-core.p0",
                "--host",
                "dry-world",
                "--proposer",
                "catalog",
                "--forks",
                "8",
                "--out",
                str(out),
                "--export",
                str(export),
            ]
        )
        self.assertEqual(rc, 0)
        rows = [json.loads(line) for line in out.read_text().splitlines()]
        hops = [r for r in rows if r["kind"] == "hop"]
        gold = [h for h in hops if h.get("sft")]
        self.assertEqual([h["target"][-1]["summary"] for h in gold], ["abs"])
        self.assertGreater(gold[0]["reward"]["advantage"], 0)
        intents = {h["input"]["intent"] for h in hops}
        self.assertEqual(len(intents), 1)
        observes = {json.dumps(h["input"]["observe"], sort_keys=True) for h in hops}
        self.assertEqual(len(observes), 1)
        for hop in hops:
            if hop["reward"]["cut"] in C.HARD_CUTS:
                self.assertFalse(hop["sft"])
                self.assertIsNotNone(drop_reason(hop))
        self.assertIsNone(drop_reason(gold[0]))
        exported = [json.loads(line) for line in export.read_text().splitlines()]
        self.assertEqual(len(exported), 1)
        self.assertIn("abs", exported[0]["messages"][2]["content"])

    def test_completions_gate_illegal_body(self):
        folder = Path(tempfile.mkdtemp())
        src = folder / "candidates.jsonl"
        lines = [
            {"plant": "arith-core.p0", "target": _abs_target()},
            {"plant": "arith-core.p0", "target": _id_target()},
            {"plant": "arith-core.p0", "target": _illegal_target()},
        ]
        src.write_text("\n".join(json.dumps(x) for x in lines) + "\n")
        out = folder / "controller.jsonl"
        rc = C.main(
            [
                "--plant",
                "arith-core.p0",
                "--host",
                "dry-world",
                "--proposer",
                "completions",
                "--completions",
                str(src),
                "--forks",
                "4",
                "--out",
                str(out),
            ]
        )
        self.assertEqual(rc, 0)
        hops = [json.loads(line) for line in out.read_text().splitlines() if '"kind": "hop"' in line or '"kind":"hop"' in line]
        hops = [h for h in hops if h["kind"] == "hop"]
        by_summary = {h["target"][-1]["summary"]: h for h in hops if h["target"]}
        self.assertTrue(by_summary["from-model"]["sft"])
        self.assertEqual(by_summary["same"]["reward"]["cut"], "identity")
        self.assertFalse(by_summary["same"]["sft"])
        self.assertEqual(by_summary["bad"]["reward"]["cut"], "schema")
        self.assertEqual(by_summary["bad"]["reward"]["r"], -20.0)
        self.assertFalse(by_summary["bad"]["sft"])

    def test_depth_and_other_project_exit_2(self):
        self.assertEqual(C.main(["--project", "twin-step", "--out", "/tmp/nope-ctl.jsonl"]), 2)
        self.assertEqual(C.main(["--depth", "2", "--out", "/tmp/nope-ctl.jsonl"]), 2)
        self.assertEqual(C.main(["--forks", "1", "--out", "/tmp/nope-ctl.jsonl"]), 2)


class ControllerAura(unittest.TestCase):
    def test_completions_on_aura(self):
        try:
            from apply import pick_bin

            pick_bin()
        except SystemExit:
            self.skipTest("aura binary missing")
        folder = Path(tempfile.mkdtemp())
        src = folder / "candidates.jsonl"
        lines = [
            {"plant": "arith-core.p0", "target": _abs_target()},
            {"plant": "arith-core.p0", "target": _id_target()},
            {"plant": "arith-core.p0", "target": RO._refuse("f", "hold")},
        ]
        src.write_text("\n".join(json.dumps(x) for x in lines) + "\n")
        out = folder / "controller.jsonl"
        rc = C.main(
            [
                "--plant",
                "arith-core.p0",
                "--host",
                "aura",
                "--proposer",
                "completions",
                "--completions",
                str(src),
                "--forks",
                "4",
                "--out",
                str(out),
            ]
        )
        self.assertEqual(rc, 0, out.read_text() if out.exists() else "no output")
        hops = [json.loads(line) for line in out.read_text().splitlines()]
        hops = [h for h in hops if h["kind"] == "hop"]
        gold = [h for h in hops if h.get("sft")]
        self.assertEqual(len(gold), 1)
        self.assertEqual(gold[0]["target"][-1]["summary"], "from-model")
        self.assertEqual(gold[0]["host"], "aura")
        self.assertGreater(gold[0]["reward"]["advantage"], 0)
