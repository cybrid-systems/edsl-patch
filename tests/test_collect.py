#!/usr/bin/env python3

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from apply import apply_patch, pick_bin
from parse_aura import extract_defines, patch_for


OLD = """
(define (kv:empty? store)
  (= (kv:size store) 0))
(define (kv:size store)
  0)
"""

NEW_BODY = "(lambda (store) (null? store))"


def aura_available() -> bool:
    try:
        pick_bin()
        return True
    except SystemExit:
        return False


class CollectShapeTests(unittest.TestCase):
    def test_old_empty_extract(self):
        defs = extract_defines(OLD)
        self.assertEqual(defs["kv:empty?"], "(lambda (store) (= (kv:size store) 0))")


@unittest.skipUnless(aura_available(), "Aura binary not found")
class CollectApplyTests(unittest.TestCase):
    def test_business_rebind_applies(self):
        target = patch_for("kv:empty?", NEW_BODY, "empty-null")
        result = apply_patch(OLD, target)
        self.assertTrue(result.get("ok"), result)
        self.assertIn("null?", result.get("source") or "")


if __name__ == "__main__":
    unittest.main()
