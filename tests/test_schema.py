#!/usr/bin/env python3
"""Schema v1.5: rebind gold, refuse gold, frozen rebind rejected."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from edsl_patch import PatchError, validate_patch
from parse_aura import patch_for


REBIND = patch_for("control", "(lambda (world) 0)", "zero-u")
REFUSE = [
    {"kind": "query", "op": "find", "name": "step"},
    {"kind": "refuse", "op": "frozen", "name": "step", "why": "integrator is frozen"},
]


class SchemaV15Tests(unittest.TestCase):
    def test_rebind_gold_ok(self):
        validate_patch(REBIND, observe={"hot": ["control"], "frozen": ["step"]})

    def test_refuse_gold_ok(self):
        validate_patch(REFUSE, observe={"hot": ["control"], "frozen": ["step"]})

    def test_synthesis_before_query_rejected(self):
        with self.assertRaises(PatchError):
            validate_patch(
                [
                    {
                        "kind": "synthesis",
                        "op": "rebind",
                        "name": "control",
                        "body": "(lambda (world) 0)",
                        "summary": "z",
                    }
                ]
            )

    def test_two_syntheses_rejected(self):
        with self.assertRaises(PatchError):
            validate_patch(REBIND + REBIND[2:])

    def test_rebind_frozen_rejected(self):
        bad = patch_for("step", "(lambda (w u) w)", "freeze-break")
        with self.assertRaises(PatchError) as ctx:
            validate_patch(bad, observe={"hot": ["control"], "frozen": ["step"]})
        self.assertIn("frozen", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
