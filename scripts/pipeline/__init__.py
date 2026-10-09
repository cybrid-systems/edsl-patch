"""Reproducible real-code collection pipeline (v2).

Stages: pick commits -> split per define -> close dependency context ->
apply on the pinned Aura + run tests -> KEEP/ROLLBACK + intent ->
dedup + holdout -> quality report -> export.

Entry: python3 -m scripts.pipeline collect --repo <path> --out <dir>
Rows keep the existing sample schema (schema/sample.md); export goes
through scripts/export_sft.py.
"""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
ROOT = SCRIPTS.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

PIPELINE_VERSION = "2.0.0"
