#!/usr/bin/env python3
"""Host apply goldens. Skips if Aura binary is missing."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from apply import apply_patch, pick_bin
from edsl_patch import load_sample, sources_match


def aura_available() -> bool:
    try:
        pick_bin()
        return True
    except SystemExit:
        return False


@unittest.skipUnless(aura_available(), "Aura binary not found")
class ApplyTests(unittest.TestCase):
    def test_identity_to_abs(self):
        sample = load_sample(ROOT / "examples" / "identity-to-abs.jsonl")
        result = apply_patch(sample["input"]["source"], sample["target"])
        self.assertTrue(result.get("ok"), result)
        expected = sample["verify"]["expected_source"]
        self.assertTrue(sources_match(result["source"], expected), result["source"])
        finds = [q for q in result["query"] if q["op"] == "find"]
        self.assertTrue(finds and finds[0]["ok"] and not finds[0]["empty"])

    def test_plus1_to_double(self):
        sample = load_sample(ROOT / "examples" / "plus1-to-double.jsonl")
        result = apply_patch(sample["input"]["source"], sample["target"])
        self.assertTrue(result.get("ok"), result)
        expected = sample["verify"]["expected_source"]
        self.assertTrue(sources_match(result["source"], expected), result["source"])


if __name__ == "__main__":
    unittest.main()
