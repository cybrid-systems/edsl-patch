#!/usr/bin/env python3

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from quality import run_filter


def sample(source, name, body, summary="s"):
    return {
        "id": f"{name}-{summary}",
        "input": {"source": source},
        "target": [
            {"kind": "query", "op": "find", "name": name},
            {"kind": "query", "op": "def-use", "name": name},
            {
                "kind": "synthesis",
                "op": "rebind",
                "name": name,
                "body": body,
                "summary": summary,
            },
        ],
    }


SRC = "(define f (lambda (x) x))"


class QualityTests(unittest.TestCase):
    def test_noop_drop(self):
        rows = [sample(SRC, "f", "(lambda (x) x)", "id")]
        kept, drops = run_filter(rows, project="p", cap=250, enforce_shape=False)
        self.assertEqual(kept, [])
        self.assertEqual(drops["noop"], 1)

    def test_dedup_drop(self):
        body = "(lambda (x) (+ x 1))"
        rows = [sample(SRC, "f", body, "plus1"), sample(SRC, "f", body, "plus1")]
        kept, drops = run_filter(rows, project="p", cap=250, enforce_shape=False)
        self.assertEqual(len(kept), 1)
        self.assertEqual(drops["dedup"], 1)

    def test_banned_token_drop(self):
        # schema rejects eval in body; token filter still counts if schema-legal
        # use source containing fiber:spawn
        src = "(define f (lambda (x) x)) ; fiber:spawn"
        rows = [sample(src, "f", "(lambda (x) (+ x 1))", "plus1")]
        kept, drops = run_filter(rows, project="p", cap=250, enforce_shape=False)
        self.assertEqual(kept, [])
        self.assertEqual(drops["token"], 1)

    def test_summary_cap_drop(self):
        rows = [
            sample(SRC, "f", f"(lambda (x) (+ x {i}))", "plusN") for i in range(5)
        ]
        kept, drops = run_filter(rows, project="p", cap=2, enforce_shape=False)
        self.assertEqual(len(kept), 2)
        self.assertEqual(drops["summary-cap"], 3)

    def test_check_identity_to_abs(self):
        r = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "quality.py"),
                "--check",
                str(ROOT / "examples" / "identity-to-abs.jsonl"),
                "--project",
                "arith-core",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)


if __name__ == "__main__":
    unittest.main()
