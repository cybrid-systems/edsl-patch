#!/usr/bin/env python3
"""Budget resolver + auto-plan defaults. No Aura host required."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import farm_budget as fb  # noqa: E402


class ResolveTests(unittest.TestCase):
    def test_default_is_smoke(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            for key in list(os.environ):
                if key.startswith("EDSL_PATCH") or key.startswith("FARM_") or key == "COLLECT_LIMIT":
                    os.environ.pop(key, None)
            got = fb.resolve()
        self.assertEqual(got["preset"], "smoke")
        self.assertEqual(got["target"], 20)
        self.assertEqual(got["max_catalog_edits"], 0)
        self.assertEqual(got["collect_limit"], 5)

    def test_cli_small_overrides_env_full(self):
        with mock.patch.dict(os.environ, {"EDSL_PATCH_BUDGET": "full"}, clear=False):
            got = fb.resolve(preset="small", allow_full=False)
        self.assertEqual(got["preset"], "small")
        self.assertEqual(got["target"], 80)
        self.assertLessEqual(got["max_loop"], 2)

    def test_target_wish_clamped_to_smoke(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("EDSL_PATCH_BUDGET", None)
            os.environ.pop("FARM_TARGET", None)
            got = fb.resolve(preset="smoke", target=3000)
        self.assertEqual(got["target"], 20)

    def test_env_full_is_explicit(self):
        with mock.patch.dict(os.environ, {"EDSL_PATCH_BUDGET": "full", "FARM_TARGET": "3000"}, clear=False):
            got = fb.resolve(allow_full=True)
        self.assertEqual(got["preset"], "full")
        self.assertEqual(got["target"], 3000)

    def test_unknown_preset_exits(self):
        with self.assertRaises(SystemExit):
            fb.resolve(preset="unlimited")


class PlanTests(unittest.TestCase):
    def test_plan_all_never_selects_full(self):
        plans = fb.plan_all()
        self.assertGreaterEqual(len(plans), 8)
        for p in plans:
            self.assertNotEqual(p["auto_preset"], "full")
            self.assertIn(p["auto_preset"], {"off", "smoke", "small", "medium"})

    def test_existing_catalog_never_full(self):
        p = fb.plan_project("arith-core")
        self.assertGreater(p["plants"], 0)
        self.assertNotEqual(p["auto_preset"], "full")

    def test_status_line_has_budget(self):
        line = fb.status_line(fb.plan_project("kv-mini"))
        self.assertIn("FARM_PLAN", line)
        self.assertIn("budget=", line)
        self.assertIn("grok_tokens_est=", line)

    def test_host_estimate_zero_without_pairs(self):
        host = fb.estimate_host(20, 0)
        self.assertEqual(host["keep_est"], 0)

    def test_grok_zero_when_host_only(self):
        b = fb.PRESETS["smoke"]
        budget = {
            "max_loop": b["max_loop"],
            "max_catalog_edits": 0,
        }
        g = fb.estimate_grok(budget, need_implement=False, catalog_edits=0)
        self.assertTrue(g["host_only"])
        self.assertEqual(g["grok_tokens_est"], 0)


if __name__ == "__main__":
    unittest.main()
