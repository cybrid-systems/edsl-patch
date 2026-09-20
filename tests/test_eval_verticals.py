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

    def test_twin_holdout_steps_not_catalog(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        from catalog import load_project
        from parse_aura import extract_defines

        def norm(s):
            return " ".join((s or "").split())

        cat = set()
        plants, _ = load_project("twin-step")
        for p in plants:
            defs = extract_defines(p["source"])
            if "step" in defs:
                cat.add(norm(defs["step"]))
        hold = ROOT / "eval" / "verticals" / "twin-holdout.jsonl"
        distinct = []
        for line in hold.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            defs = extract_defines(row["input"]["source"])
            step = defs.get("step")
            if not step:
                continue
            self.assertNotIn(norm(step), cat, row["id"])
            distinct.append(norm(step))
        self.assertGreaterEqual(len(set(distinct)), 4)
        readme = (ROOT / "eval" / "verticals" / "README.md").read_text(encoding="utf-8")
        self.assertIn("export_sft", readme)
        self.assertIn("never", readme.lower())

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
