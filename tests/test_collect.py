#!/usr/bin/env python3

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from apply import apply_patch, pick_bin
from collect import (
    child_only_helpers,
    doctor,
    drop_ambiguous,
    make_intent,
    noise_reason,
    reject_change,
    semantic_summary,
)
from collections import Counter
from parse_aura import (
    bodies_equivalent,
    code_symbols,
    extract_defines,
    focused_source,
    paren_balanced,
    patch_for,
)


OLD = """
(define (kv:empty? store)
  (= (kv:size store) 0))
(define (kv:size store)
  0)
"""

NEW_BODY = "(lambda (store) (null? store))"


def aura_available() -> bool:
    try:
        pick_bin()
        return True
    except SystemExit:
        return False


class CollectShapeTests(unittest.TestCase):
    def test_old_empty_extract(self):
        defs = extract_defines(OLD)
        self.assertEqual(defs["kv:empty?"], "(lambda (store) (= (kv:size store) 0))")

    def test_doctor_no_jsonl_exit_0(self):
        import contextlib
        import io
        from pathlib import Path as P

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = doctor(
                parent=P("/tmp"),
                globs=["no-such/*.aura"],
                cursor=P("/tmp/edsl-no-cursor.json"),
            )
        self.assertEqual(rc, 0)
        text = buf.getvalue()
        self.assertIn("doctor: aura-bin", text)
        self.assertIn("doctor: glob no-such/*.aura matches=", text)
        self.assertIn("doctor: sibling unify git=", text)
        self.assertNotIn("collect: keep", text)


@unittest.skipUnless(aura_available(), "Aura binary not found")
class CollectApplyTests(unittest.TestCase):
    def test_business_rebind_applies(self):
        target = patch_for("kv:empty?", NEW_BODY, "empty-null")
        result = apply_patch(OLD, target)
        self.assertTrue(result.get("ok"), result)
        self.assertIn("null?", result.get("source") or "")


PARENT = """
(define (store-get db key)
  (hash-ref db key))
(define (store-size db)
  0)
"""

CHILD = """
(define (store-touch! db key)
  db)
(define (store-get db key)
  (store-touch! db key))
(define (store-size db)
  1)
"""

KV = """
(define (kv:size store)
  0)
(define (kv:empty? store)
  (= (kv:size store) 0))
"""


class CollectFocusTests(unittest.TestCase):
    def test_child_helper_is_rejected(self):
        body = extract_defines(CHILD)["store-get"]
        self.assertIn("store-touch!", child_only_helpers(PARENT, CHILD, body, "store-get"))
        self.assertEqual(
            reject_change("store-get", "src/redis/store.aura", PARENT, CHILD, extract_defines(PARENT)["store-get"], body),
            "child-helper",
        )

    def test_string_and_comment_are_not_calls(self):
        src = '(lambda (x) "store-touch!" x) ; store-touch!'
        self.assertNotIn("store-touch!", code_symbols(src))

    def test_comment_only_change_rejected(self):
        old = "(lambda (db key) (hash-ref db key))"
        new = "(lambda (db key) (hash-ref db key)) ; later"
        self.assertTrue(bodies_equivalent(old, new))
        self.assertEqual(
            reject_change("store-get", "store.aura", PARENT, PARENT, old, new),
            "comment-only",
        )

    def test_unbalanced_and_stamp(self):
        self.assertFalse(paren_balanced("(lambda (x) (+ x 1)"))
        self.assertEqual(noise_reason("stamp-info", "aura/self_evolve_stamp.aura", "(lambda () 0)"), "stamp")
        self.assertEqual(noise_reason("run", "a.aura", '(lambda () (hash "traj_id" "ep-1"))'), "stamp")

    def test_focus_keeps_user_and_callee_signature(self):
        text = focused_source(KV, "kv:size")
        self.assertIn("(define kv:size (lambda (store) 0))", text)
        self.assertIn("(define kv:empty?", text)
        sig = focused_source(KV, "kv:empty?")
        self.assertIn("(define kv:size (lambda (store) #f))", sig)
        self.assertNotIn("(lambda (store) 0)", sig)

    def test_intent_and_summary_come_from_the_subject(self):
        self.assertEqual(
            semantic_summary("perf(redis): memtier hot-path opts — p=1"),
            "memtier hot-path opts — p=1",
        )
        self.assertNotRegex(semantic_summary("adjust ttl @abc1234"), r"@[0-9a-f]{7}")
        intent = make_intent("store-get", "v0.2 commands, lazy TTL", "Touch keys on read.\n\nSigned-off-by: dev")
        self.assertIn("store-get", intent)
        self.assertIn("lazy TTL", intent)
        self.assertIn("Touch keys", intent)
        self.assertNotIn("Signed-off-by", intent)

    def test_abs_path_rejected(self):
        from collect import _has_abs_path

        self.assertTrue(_has_abs_path('(pad:time-open! "/workspace/aura-pad/out/book")'))
        self.assertTrue(_has_abs_path("(open \"/home/dev/x\")"))
        self.assertFalse(_has_abs_path("(define (f x) x)"))

    def test_business_track_is_focused(self):
        path = ROOT / "data" / "raw" / "business.jsonl"
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertGreaterEqual(len(rows), 1)
        prompts = set()
        for row in rows:
            self.assertTrue((row.get("input") or {}).get("intent"))
            summary = row["target"][-1]["summary"]
            self.assertNotRegex(summary, r"@[0-9a-fA-F]{7}")
            self.assertLessEqual(len(row["input"]["source"]), 12000)
            self.assertNotIn("/workspace/", row["input"]["source"])
            self.assertNotIn("/home/", row["input"]["source"])
            self.assertEqual((row.get("meta") or {}).get("focus"), "define+def-use")
            key = (row["input"]["source"], row["input"]["intent"])
            self.assertNotIn(key, prompts)
            prompts.add(key)
        self.assertFalse((ROOT / "data" / "raw" / "business-clean.jsonl").exists())

    def test_ambiguous_prompt_dropped(self):
        drops = Counter()
        rows = drop_ambiguous(
            [
                {"source": "(define f (lambda (x) x))", "intent": "Rebind f: add one", "body": "(lambda (x) (+ x 1))"},
                {"source": "(define f (lambda (x) x))", "intent": "Rebind f: add one", "body": "(lambda (x) (+ x 2))"},
                {"source": "(define f (lambda (x) x))", "intent": "Rebind f: abs", "body": "(lambda (x) x)"},
            ],
            drops,
        )
        self.assertEqual(drops["ambiguous"], 2)
        self.assertEqual(len(rows), 1)
        self.assertIn("abs", rows[0]["intent"])


if __name__ == "__main__":
    unittest.main()
