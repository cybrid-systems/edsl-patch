#!/usr/bin/env python3
"""Farm legal-only tests always run; host tests skip without Aura."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from apply import apply_patch, pick_bin
from catalog import load_rewrites
from edsl_patch import PatchError, lesson_to_sample, sources_match, validate_patch
from farm import parse_stdout, run_aura, spot_check
from parse_aura import patch_for


def aura_available() -> bool:
    try:
        pick_bin()
        return True
    except SystemExit:
        return False


class WorldKeepTests(unittest.TestCase):
    def test_twin_keep_drop(self):
        from farm import twin_should_keep

        self.assertTrue(twin_should_keep(40, 80, 40, 10.0, 3.0, "control", ["step"]))
        self.assertFalse(twin_should_keep(40, 80, 40, 10.0, 12.0, "control", ["step"]))
        self.assertFalse(twin_should_keep(40, 80, 40, 10.0, 3.0, "step", ["step"]))

    def test_session_keep_drop(self):
        from farm import session_should_keep

        s = {"id": 1, "fd": 7, "alive": True}
        self.assertTrue(session_should_keep(s, s, "quote"))
        self.assertFalse(session_should_keep(s, {"id": 1, "fd": 7, "alive": False}, "quote"))
        self.assertFalse(session_should_keep(s, s, "*session*"))


class FarmLegalTests(unittest.TestCase):
    def test_help_documents_path_mode(self):
        import farm as farm_mod
        from io import StringIO
        from unittest.mock import patch

        buf = StringIO()
        with patch("sys.stdout", buf):
            try:
                farm_mod.main(["--help"])
            except SystemExit as e:
                self.assertEqual(e.code, 0)
        self.assertIn("--mode", buf.getvalue())
        self.assertIn("path", buf.getvalue())

    def test_farm_aura_has_no_fiber_spawn(self):
        text = (ROOT / "lib" / "farm.aura").read_text(encoding="utf-8")
        self.assertNotIn("fiber:spawn", text)
    def test_catalog_rewrites_are_legal_patches(self):
        for rw in load_rewrites():
            validate_patch(patch_for(rw["name"], rw["body"], rw["summary"]))
            self.assertEqual(patch_for(rw["name"], rw["body"], rw["summary"])[-1]["op"], "rebind")

    def test_define_in_body_rejected(self):
        with self.assertRaises(PatchError):
            validate_patch(
                patch_for("f", "(lambda (x) (define y 1) x)", "bad")
            )

    def test_eval_body_rejected(self):
        with self.assertRaises(PatchError):
            validate_patch(patch_for("f", "(lambda (x) (eval x))", "eval"))

    def test_sample_shape_query_then_rebind(self):
        sample = lesson_to_sample(
            {
                "id": "t",
                "name": "f",
                "params": "x",
                "summary": "plus1",
                "inner0": "x",
                "inner1": "(+ x 1)",
                "helpers": "",
                "sugar": False,
            }
        )
        target = sample["target"]
        self.assertEqual(target[-1]["kind"], "synthesis")
        self.assertTrue(all(s["kind"] == "query" for s in target[:-1]))
        finds = [s for s in target if s.get("op") == "find"]
        self.assertEqual(finds[0]["name"], target[-1]["name"])


@unittest.skipUnless(aura_available(), "Aura binary not found")
class FarmHostTests(unittest.TestCase):
    def test_farm_rounds_6_apply_ok(self):
        import farm as farm_mod

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "farm.jsonl"
            observe = Path(tmp) / "observe.jsonl"
            rc = farm_mod.main(
                [
                    "--rounds",
                    "6",
                    "--timeout",
                    "60",
                    "--out",
                    str(out),
                    "--observe",
                    str(observe),
                ]
            )
            self.assertEqual(rc, 0)
            rows = [json.loads(l) for l in out.read_text().splitlines() if l.strip()]
            self.assertGreaterEqual(len(rows), 1)
            for row in rows:
                result = apply_patch(row["input"]["source"], row["target"])
                self.assertTrue(result.get("ok"), row["id"])
            self.assertEqual(spot_check(out, 1.0), 0)
            for row in rows:
                expected = (row.get("verify") or {}).get("expected_source")
                if expected:
                    result = apply_patch(row["input"]["source"], row["target"])
                    self.assertTrue(
                        sources_match(result.get("source") or "", expected),
                        row["id"],
                    )

    def test_path_mode_3_step_chain(self):
        import farm as farm_mod

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "farm.jsonl"
            observe = Path(tmp) / "observe.jsonl"
            rc = farm_mod.main(
                [
                    "--mode",
                    "path",
                    "--depth",
                    "3",
                    "--rounds",
                    "3",
                    "--timeout",
                    "60",
                    "--out",
                    str(out),
                    "--observe",
                    str(observe),
                ]
            )
            self.assertEqual(rc, 0)
            rows = [json.loads(l) for l in out.read_text().splitlines() if l.strip()]
            self.assertGreaterEqual(len(rows), 3)
            chain = rows[:3]
            for i, row in enumerate(chain):
                self.assertEqual(row.get("meta", {}).get("mode"), "path")
                self.assertEqual(row.get("meta", {}).get("round"), i + 1)
                self.assertNotIn("fiber:spawn", json.dumps(row))
            for i in range(2):
                prev = chain[i]["verify"]["expected_source"]
                nxt = chain[i + 1]["input"]["source"]
                self.assertTrue(sources_match(prev, nxt), f"chain {i}->{i+1}")

    def test_missing_name_is_observe_not_sample(self):
        driver = """
(require "farm" all:)
(display "EDSL_PLANT id-f")
(newline)
(farm:run "(define f (lambda (x) x))"
  (list (hash "name" "missing" "body" "(lambda (x) x)" "summary" "no-find")))
"""
        out = run_aura(driver, timeout=30)
        samples, observes = parse_stdout(out)
        self.assertEqual(samples, [])
        self.assertGreaterEqual(len(observes), 1)
        self.assertEqual(observes[0].get("reason"), "find-empty")


if __name__ == "__main__":
    unittest.main()
