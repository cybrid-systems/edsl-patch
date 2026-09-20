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


class FarmLegalTests(unittest.TestCase):
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
