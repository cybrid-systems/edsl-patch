#!/usr/bin/env python3
"""Catalog --check is legal-only and needs no Aura host."""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from catalog import check, load_plants, load_rewrites, pairs
from edsl_patch import validate_patch
from parse_aura import patch_for


class CatalogTests(unittest.TestCase):
    def test_check_cli_exits_0(self):
        r = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "catalog.py"), "--check"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("catalog: ok", r.stdout)

    def test_every_rewrite_is_legal_patch(self):
        for rw in load_rewrites():
            validate_patch(patch_for(rw["name"], rw["body"], rw["summary"]))
            self.assertNotIn("(define", rw["body"])
            self.assertNotIn("eval", rw["body"])

    def test_plants_and_pairs(self):
        plants = load_plants()
        rewrites = load_rewrites()
        self.assertGreaterEqual(len(plants), 6)
        self.assertGreaterEqual(len(rewrites), 8)
        errs = check(plants, rewrites)
        self.assertEqual(errs, [])
        self.assertGreater(len(pairs(plants, rewrites)), 0)
        sugar = next(p for p in plants if p["id"] == "sugar-f")
        self.assertIn("(define (f x)", sugar["source"])

    def test_projects_check(self):
        r = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "catalog.py"), "--check", "--projects"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("catalog: ok projects=8", r.stdout)
        orch = (ROOT / "catalog" / "projects" / "orch-pure" / "plants.jsonl").read_text()
        self.assertNotIn("agent:", orch)
        self.assertNotIn("fiber:", orch)


if __name__ == "__main__":
    unittest.main()
