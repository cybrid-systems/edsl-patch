#!/usr/bin/env python3

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from parse_aura import extract_defines, patch_for, sugar_to_lambda


SNIPPET = """
; comment
(export kv:get kv:empty?)
(define (kv:open)
  (quote ()))
(define (kv:get store key)
  (kv:_ref store key))
(define kv:empty? (lambda (store) (null? store)))
(define kv:version 16)
"""


class ParseTests(unittest.TestCase):
    def test_snippet(self):
        defs = extract_defines(SNIPPET)
        self.assertEqual(defs["kv:open"], "(lambda () (quote ()))")
        self.assertEqual(defs["kv:get"], "(lambda (store key) (kv:_ref store key))")
        self.assertEqual(defs["kv:empty?"], "(lambda (store) (null? store))")
        self.assertNotIn("kv:version", defs)

    def test_sugar_to_lambda(self):
        self.assertEqual(
            sugar_to_lambda("store key", "(kv:_ref store key)"),
            "(lambda (store key) (kv:_ref store key))",
        )

    def test_patch_for(self):
        p = patch_for("kv:get", "(lambda (store key) (kv:_ref store key))", "get")
        self.assertEqual(p[0]["name"], "kv:get")
        self.assertEqual(p[-1]["op"], "rebind")


class KvFileTests(unittest.TestCase):
    def test_kv_plant_parses(self):
        path = ROOT.parent / "unify" / "projects" / "kv" / "lib" / "kv.aura"
        if not path.is_file():
            self.skipTest("unify kv.aura not checked out")
        defs = extract_defines(path.read_text(encoding="utf-8"))
        self.assertGreater(len(defs), 40)
        self.assertIn("kv:get", defs)
        self.assertIn("kv:set", defs)
        self.assertTrue(defs["kv:get"].startswith("(lambda"))


if __name__ == "__main__":
    unittest.main()
