#!/usr/bin/env python3

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class FarmLoopTests(unittest.TestCase):
    def test_help_documents_budget(self):
        r = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "farm_loop.py"), "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(r.returncode, 0)
        self.assertIn("--budget", r.stdout)
        self.assertIn("EDSL_PATCH_BUDGET", r.stdout)

    def test_unknown_project_exits_2(self):
        r = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "farm_loop.py"), "--project", "nope"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main()
