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

    def test_twin_damp_probes(self):
        from apply import apply_sample

        sample = load_sample(ROOT / "examples" / "twin-damp.jsonl")
        result = apply_sample(sample)
        self.assertTrue(result.get("ok"), result)
        self.assertTrue(result.get("probe_pass"), result)

    def test_twin_refuse_noop(self):
        from apply import apply_sample

        sample = load_sample(ROOT / "examples" / "twin-refuse-step.jsonl")
        result = apply_sample(sample)
        self.assertTrue(result.get("ok"), result)
        self.assertTrue(sources_match(result["source"], sample["input"]["source"]) or "step" in result["source"])

    def test_twin_energy_not_dropped_fails(self):
        from apply import apply_sample, twin_probes

        sample = load_sample(ROOT / "examples" / "twin-damp.jsonl")
        # zero-u on already-zero control: energy does not drop below start
        bad = dict(sample)
        bad["target"] = [
            {"kind": "query", "op": "find", "name": "control"},
            {"kind": "query", "op": "def-use", "name": "control"},
            {
                "kind": "synthesis",
                "op": "rebind",
                "name": "control",
                "body": "(lambda (world) 0)",
                "summary": "zero-u",
            },
        ]
        bad["verify"] = {
            "apply_ok": True,
            "probes": {"t_mono": True, "energy_after_steps_lt": 0.5},
        }
        result = apply_sample(bad)
        self.assertFalse(result.get("ok"))

    def test_session_identity_fail(self):
        from apply import apply_sample

        sample = load_sample(ROOT / "examples" / "session-narrow.jsonl")
        bad = dict(sample)
        bad["input"] = dict(sample["input"])
        bad["input"]["observe"] = {
            "session": {"id": 99, "fd": 1, "alive": True},
            "hot": ["quote"],
            "frozen": ["*session*"],
        }
        result = apply_sample(bad)
        self.assertFalse(result.get("ok"))


if __name__ == "__main__":
    unittest.main()
