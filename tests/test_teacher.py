#!/usr/bin/env python3
"""Teacher seeds apply; Aura multi-agent fanout yields ≥4× unique verified rows."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from apply import apply_patch, pick_bin
from edsl_patch import lesson_to_sample, validate_patch
from teach import read_jsonl, run_teacher, verify_lessons

SEEDS = ROOT / "lessons" / "seeds.jsonl"


def aura_available() -> bool:
    try:
        pick_bin()
        return True
    except SystemExit:
        return False


class SeedLegalTests(unittest.TestCase):
    def test_every_seed_is_legal(self):
        seeds = read_jsonl(SEEDS)
        self.assertGreaterEqual(len(seeds), 8)
        for les in seeds:
            sample = lesson_to_sample(les)
            validate_patch(sample["target"])
            self.assertEqual(sample["target"][0]["op"], "find")
            self.assertEqual(sample["target"][-1]["op"], "rebind")


@unittest.skipUnless(aura_available(), "Aura binary not found")
class SeedApplyTests(unittest.TestCase):
    def test_every_seed_applies(self):
        for les in read_jsonl(SEEDS):
            sample = lesson_to_sample(les)
            result = apply_patch(sample["input"]["source"], sample["target"])
            self.assertTrue(result.get("ok"), f"{les['id']}: {result}")
            self.assertIn(les["inner1"], result.get("source") or "")


@unittest.skipUnless(aura_available(), "Aura binary not found")
class FanoutTests(unittest.TestCase):
    def test_agent_fanout_volume(self):
        seeds = read_jsonl(SEEDS)
        mode, lessons = run_teacher(seeds)
        self.assertEqual(mode, "agent-ask-yield")
        self.assertGreaterEqual(len(lessons), 4 * len(seeds))
        raw = "\n".join(json.dumps(x) for x in lessons)
        self.assertNotIn("mutate:rebind", raw)
        kept = verify_lessons(lessons)
        self.assertGreaterEqual(len(kept), 4 * len(seeds), f"verified={len(kept)}")
        ids = {row["id"] for row in kept}
        self.assertIn("abs", ids)
        self.assertTrue(any(i.startswith("abs.namer.") for i in ids))
        self.assertTrue(any(".helper." in i for i in ids))
        self.assertTrue(any(".binder." in i for i in ids))


if __name__ == "__main__":
    unittest.main()
