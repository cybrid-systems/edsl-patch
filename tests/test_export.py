#!/usr/bin/env python3
"""SFT export strips verify and refuses illegal rows."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from edsl_patch import PatchError
from export_sft import to_sft


class ExportTests(unittest.TestCase):
    def test_strips_verify(self):
        sample = json.loads(
            (ROOT / "examples" / "identity-to-abs.jsonl").read_text(encoding="utf-8")
        )
        row = to_sft(sample)
        self.assertNotIn("verify", row)
        self.assertEqual(len(row["messages"]), 3)
        self.assertEqual(row["messages"][1]["content"], sample["input"]["source"])
        target = json.loads(row["messages"][2]["content"])
        self.assertEqual(target[-1]["op"], "rebind")

    def test_illegal_not_exported(self):
        sample = json.loads(
            (ROOT / "examples" / "legacy-control" / "poison-eval-rebind.jsonl").read_text(
                encoding="utf-8"
            )
        )
        with self.assertRaises(PatchError):
            to_sft(sample)
        self.assertIs(sample.get("sft"), False)

    def test_farm_shaped_row_strips_verify(self):
        sample = {
            "id": "farm-id-f-plus1-f",
            "input": {"source": "(define f (lambda (x) x))"},
            "target": [
                {"kind": "query", "op": "find", "name": "f"},
                {"kind": "query", "op": "def-use", "name": "f"},
                {
                    "kind": "synthesis",
                    "op": "rebind",
                    "name": "f",
                    "body": "(lambda (x) (+ x 1))",
                    "summary": "plus1",
                },
            ],
            "verify": {
                "apply_ok": True,
                "expected_source": "(define f (lambda (x) (+ x 1)))",
            },
        }
        row = to_sft(sample)
        self.assertNotIn("verify", row)
        target = json.loads(row["messages"][2]["content"])
        self.assertIsInstance(target, list)
        self.assertEqual(target[-1]["op"], "rebind")
        self.assertEqual(target[-1]["summary"], "plus1")


if __name__ == "__main__":
    unittest.main()
