#!/usr/bin/env python3
"""SFT export strips verify and refuses illegal rows."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from edsl_patch import PatchError
from export_sft import to_sft


class ExportTests(unittest.TestCase):
    def test_strips_verify(self):
        sample = json.loads(
            (ROOT / "examples" / "identity-to-abs.jsonl").read_text(encoding="utf-8")
        )
        row = to_sft(sample)
        self.assertNotIn("verify", row)
        self.assertEqual(len(row["messages"]), 3)
        self.assertEqual(row["messages"][1]["content"], sample["input"]["source"])
        target = json.loads(row["messages"][2]["content"])
        self.assertEqual(target[-1]["op"], "rebind")

    def test_illegal_not_exported(self):
        sample = json.loads(
            (ROOT / "examples" / "legacy-control" / "poison-eval-rebind.jsonl").read_text(
                encoding="utf-8"
            )
        )
        with self.assertRaises(PatchError):
            to_sft(sample)
        self.assertIs(sample.get("sft"), False)

    def test_poison_eval_not_in_commercial(self):
        import tempfile
        from export_sft import main as export_main

        out = Path(tempfile.mkdtemp()) / "sft.jsonl"
        rc = export_main(
            [
                "--profile",
                "commercial",
                "--allow-partial",
                "--out",
                str(out),
                str(ROOT / "tests" / "fixtures" / "export" / "twin.jsonl"),
                str(ROOT / "tests" / "fixtures" / "export" / "refuse.jsonl"),
                str(ROOT / "tests" / "fixtures" / "export" / "poison.jsonl"),
            ]
        )
        self.assertEqual(rc, 0)
        text = out.read_text()
        self.assertNotIn("eval x", text)
        self.assertIn("refuse", text)

    def test_farm_shaped_row_strips_verify(self):
        sample = {
            "id": "farm-id-f-plus1-f",
            "input": {"source": "(define f (lambda (x) x))"},
            "target": [
                {"kind": "query", "op": "find", "name": "f"},
                {"kind": "query", "op": "def-use", "name": "f"},
                {
                    "kind": "synthesis",
                    "op": "rebind",
                    "name": "f",
                    "body": "(lambda (x) (+ x 1))",
                    "summary": "plus1",
                },
            ],
            "verify": {
                "apply_ok": True,
                "expected_source": "(define f (lambda (x) (+ x 1)))",
            },
        }
        row = to_sft(sample)
        self.assertNotIn("verify", row)
        target = json.loads(row["messages"][2]["content"])
        self.assertIsInstance(target, list)
        self.assertEqual(target[-1]["op"], "rebind")
        self.assertEqual(target[-1]["summary"], "plus1")

    def test_commercial_empty_verticals_exit_2(self):
        import tempfile
        from export_sft import main as export_main

        out = Path(tempfile.mkdtemp()) / "sft.jsonl"
        rc = export_main(
            [
                "--profile",
                "commercial",
                "--out",
                str(out),
                str(ROOT / "tests" / "fixtures" / "export" / "refuse.jsonl"),
            ]
        )
        self.assertEqual(rc, 2)

    def test_quote_only_session_dropped(self):
        from export_sft import drop_reason

        sample = {
            "id": "old-quote",
            "input": {
                "source": '(define *session* (hash "id" 1 "fd" 7 "alive" #t))\n(define quote (lambda (book) 0))',
                "observe": {
                    "session": {"id": 1, "fd": 7, "alive": True},
                    "hot": ["quote"],
                    "frozen": ["*session*"],
                },
            },
            "target": [
                {"kind": "query", "op": "find", "name": "quote"},
                {
                    "kind": "synthesis",
                    "op": "rebind",
                    "name": "quote",
                    "body": "(lambda (book) 1)",
                    "summary": "narrow",
                },
            ],
            "verify": {"apply_ok": True, "probes": {"session_stable": True}},
            "sft": True,
        }
        self.assertEqual(drop_reason(sample), "quote-only-session")

    def test_rollout_hops_only_good_exported(self):
        import tempfile
        from export_sft import drop_reason, main as export_main

        rows = [
            json.loads(l)
            for l in (ROOT / "tests" / "fixtures" / "export" / "rollout-twin.jsonl")
            .read_text()
            .splitlines()
            if l.strip()
        ]
        kinds = {r["id"]: drop_reason(r) for r in rows}
        self.assertIsNone(kinds["good-hop"])
        self.assertEqual(kinds["traj-only"], "traj")
        self.assertEqual(kinds["kill-hop"], "hop-sft-false")
        out = Path(tempfile.mkdtemp()) / "sft.jsonl"
        rc = export_main(
            [
                "--profile",
                "commercial",
                "--allow-partial",
                "--out",
                str(out),
                str(ROOT / "tests" / "fixtures" / "export" / "rollout-twin.jsonl"),
                str(ROOT / "tests" / "fixtures" / "export" / "refuse.jsonl"),
            ]
        )
        self.assertEqual(rc, 0)
        text = out.read_text()
        self.assertIn("damp-v", text)
        self.assertIn("energy 9.0 at t=40", text)
        self.assertNotIn("kill-alive", text)
        self.assertNotIn("traj-only", text)
        self.assertEqual(len([l for l in text.splitlines() if l.strip()]), 2)

    def test_arith_rollout_hop_is_dialect(self):
        from export_sft import bucket_of, drop_reason

        sample = {
            "id": "arith-hop",
            "kind": "hop",
            "sft": True,
            "input": {
                "source": "(define f (lambda (x) x))",
                "intent": "arith grid; abs",
                "observe": {"vals": [-3, -1, 0, 1, 2], "hot": ["f"], "epoch": 1},
            },
            "target": [
                {"kind": "query", "op": "find", "name": "f"},
                {"kind": "query", "op": "def-use", "name": "f"},
                {
                    "kind": "synthesis",
                    "op": "rebind",
                    "name": "f",
                    "body": "(lambda (x) (if (< x 0) (* x -1) x))",
                    "summary": "abs",
                },
            ],
            "reward": {"r": 5.0, "advantage": 1.2},
            "verify": {"apply_ok": True, "probes": {"arith_grid": True}},
        }
        self.assertIsNone(drop_reason(sample))
        self.assertEqual(
            bucket_of(ROOT / "data" / "raw" / "rollout-arith-core.jsonl", sample),
            "dialect",
        )

    def test_demo_observe_12_4_dropped(self):
        from export_sft import drop_reason

        sample = {
            "id": "demo",
            "input": {
                "source": "(define step (lambda (w u) w))\n(define control (lambda (w) 0))",
                "observe": {
                    "t": 40,
                    "energy": 12.4,
                    "hot": ["control"],
                    "frozen": ["step"],
                },
            },
            "target": [
                {"kind": "query", "op": "find", "name": "control"},
                {"kind": "query", "op": "def-use", "name": "control"},
                {
                    "kind": "synthesis",
                    "op": "rebind",
                    "name": "control",
                    "body": "(lambda (w) 0)",
                    "summary": "zero-u",
                },
            ],
            "verify": {"apply_ok": True, "probes": {"t_mono": True}},
            "sft": True,
        }
        self.assertEqual(drop_reason(sample), "demo-observe")


if __name__ == "__main__":
    unittest.main()
