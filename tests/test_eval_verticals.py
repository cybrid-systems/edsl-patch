#!/usr/bin/env python3

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class EvalVerticalsTests(unittest.TestCase):
    def test_doctor_no_overlap(self):
        r = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "eval_verticals.py"), "--doctor"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)

    def test_frozen_escape_fails(self):
        bad = {
            "id": "hold-ref-0",
            "target": [
                {"kind": "query", "op": "find", "name": "step"},
                {
                    "kind": "synthesis",
                    "op": "rebind",
                    "name": "step",
                    "body": "(lambda (w u) w)",
                    "summary": "bad",
                },
            ],
        }
        tmp = Path(tempfile.mkdtemp()) / "comp.jsonl"
        tmp.write_text(json.dumps(bad) + "\n", encoding="utf-8")
        r = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "eval_verticals.py"),
                "--completions",
                str(tmp),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()
