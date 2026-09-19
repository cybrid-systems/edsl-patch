#!/usr/bin/env python3
"""Legal-op filter: goldens parse; illegal patches refuse."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from edsl_patch import PatchError, load_sample, validate_patch


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class LegalTests(unittest.TestCase):
    def test_identity_to_abs_is_legal(self):
        sample = load_sample(ROOT / "examples" / "identity-to-abs.jsonl")
        self.assertEqual(sample["target"][-1]["op"], "rebind")
        self.assertEqual(sample["target"][0]["op"], "find")

    def test_plus1_to_double_is_legal(self):
        sample = load_sample(ROOT / "examples" / "plus1-to-double.jsonl")
        self.assertEqual(sample["target"][-1]["summary"], "double")

    def test_illegal_eval_refused(self):
        rec = read_jsonl(ROOT / "examples" / "illegal-eval.jsonl")[0]
        with self.assertRaises(PatchError) as ctx:
            validate_patch(rec["target"])
        self.assertIn("eval", str(ctx.exception))

    def test_synthesis_before_query_refused(self):
        with self.assertRaises(PatchError):
            validate_patch(
                [
                    {
                        "kind": "synthesis",
                        "op": "rebind",
                        "name": "f",
                        "body": "(lambda (x) x)",
                        "summary": "id",
                    }
                ]
            )

    def test_node_id_query_refused(self):
        with self.assertRaises(PatchError):
            validate_patch(
                [
                    {"kind": "query", "op": "find", "name": "f", "node": 2},
                    {
                        "kind": "synthesis",
                        "op": "rebind",
                        "name": "f",
                        "body": "(lambda (x) x)",
                        "summary": "id",
                    },
                ]
            )

    def test_skip_op_refused(self):
        with self.assertRaises(PatchError):
            validate_patch([{"kind": "query", "op": "skip", "name": "f"}])

    def test_define_in_body_refused(self):
        with self.assertRaises(PatchError):
            validate_patch(
                [
                    {"kind": "query", "op": "find", "name": "f"},
                    {
                        "kind": "synthesis",
                        "op": "rebind",
                        "name": "f",
                        "body": "(lambda (x) (define y 1) x)",
                        "summary": "bad",
                    },
                ]
            )

    def test_rebind_requires_matching_find(self):
        with self.assertRaises(PatchError):
            validate_patch(
                [
                    {"kind": "query", "op": "root"},
                    {
                        "kind": "synthesis",
                        "op": "rebind",
                        "name": "f",
                        "body": "(lambda (x) x)",
                        "summary": "id",
                    },
                ]
            )


if __name__ == "__main__":
    unittest.main()
