#!/usr/bin/env python3
"""Tests for the v2 collection pipeline (scripts/pipeline). Runs under pytest or unittest."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.pipeline import context as ctxm  # noqa: E402
from scripts.pipeline import host as hostm  # noqa: E402
from scripts.pipeline import intent as intm  # noqa: E402
from scripts.pipeline import label as labm  # noqa: E402
from scripts.pipeline import report as repm  # noqa: E402
from scripts.pipeline import split as splm  # noqa: E402
from scripts.pipeline import units as unm  # noqa: E402


def git(repo: Path, *args: str) -> str:
    env = os.environ | {
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
    }
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True, env=env)


def make_repo(tmp: Path, commits: list[dict[str, str]]) -> Path:
    repo = tmp / "demo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    for i, files in enumerate(commits):
        for rel, text in files.items():
            p = repo / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", f"c{i}", "--date", f"2026-01-0{i + 1}T00:00:00")
    return repo


LIB0 = """(require "std/string" all:)
(define *limit* 10)
(define *table* (list *limit* 2))
(define (h:clamp x) (if (> x *limit*) *limit* x))
(define (h:deep y) (h:clamp y))
"""
MAIN0 = """(load "/workspace/demo/src/lib.aura")
;; main
(define (m:step x) (+ x 1))
(define (m:user z) (m:step z))
(define (m:stamp-info) "abc1234")
(define m:speed 3)
(define (m:note x) x)
"""
MAIN1 = MAIN0.replace("(define (m:step x) (+ x 1))", "(define (m:step x) (h:clamp (+ x 1)))").replace(
    '"abc1234"', '"def5678"'
).replace("(define m:speed 3)", "(define m:speed 4)").replace(
    "(define (m:note x) x)", "(define (m:note x)\n  ;; comment only\n  x)"
)
MAIN2 = MAIN1.replace("(define (m:user z) (m:step z))", "(define (m:user z) (m:new (m:step z)))") + "(define (m:new q) (* q 2))\n"
TEST0 = """(load "/workspace/demo/src/main.aura")
(display "T STEP OK")
(newline)
(display "DEMO_TEST_OK")
(newline)
"""


class UnitsTest(unittest.TestCase):
    def test_classify_forms(self):
        forms = unm.top_forms(LIB0 + MAIN0)
        kinds = Counter(f.kind for f in forms)
        self.assertEqual(kinds["require"], 1)
        self.assertEqual(kinds["load"], 1)
        dm = unm.define_map(LIB0)
        self.assertEqual(dm["*limit*"].kind, "define-var")
        self.assertEqual(dm["h:clamp"].kind, "define-fn")
        self.assertEqual(dm["h:clamp"].body, "(lambda (x) (if (> x *limit*) *limit* x))")
        self.assertEqual(dm["h:clamp"].params, "(x)")

    def test_metadata_only(self):
        self.assertTrue(unm.metadata_only('(lambda () "abc1234")', '(lambda () "def5678")'))
        self.assertFalse(unm.metadata_only("(lambda (x) (+ x 1))", "(lambda (x) (+ x 2))"))

    def test_harness_files(self):
        self.assertTrue(unm.is_harness("soft/pad/gap_test.aura"))
        self.assertTrue(unm.is_harness("tests/test_resp.aura"))
        self.assertTrue(unm.is_harness("soft/pad/m3_smoke.aura"))
        self.assertFalse(unm.is_harness("src/redis/resp.aura"))

    def test_split_commit_units_and_skips(self):
        with tempfile.TemporaryDirectory() as td:
            repo = make_repo(
                Path(td),
                [
                    {"src/lib.aura": LIB0, "src/main.aura": MAIN0, "src/main_test.aura": TEST0},
                    {"src/main.aura": MAIN1, "src/main_test.aura": TEST0 + ";; x\n"},
                    {"src/main.aura": MAIN2},
                ],
            )
            commits = unm.list_commits(repo)
            self.assertEqual(len(commits), 2)
            counts: dict[str, int] = {}
            u1 = unm.split_commit(repo, "demo", commits[0], counts)
            self.assertEqual([u.name for u in u1], ["m:step"])
            self.assertEqual(u1[0].commit_group, f"demo@{commits[0].sha[:12]}")
            self.assertEqual(counts.get("skip:metadata"), 1)
            self.assertEqual(counts.get("skip:non-lambda"), 1)
            self.assertEqual(counts.get("skip:comment-or-whitespace"), 1)
            self.assertEqual(counts.get("files-harness"), 1)
            u2 = unm.split_commit(repo, "demo", commits[1], counts)
            self.assertEqual([u.name for u in u2], ["m:user"])
            self.assertEqual(u2[0].info.get("added_refs"), ["m:new"])
            c2: dict[str, int] = {}
            self.assertEqual(unm.split_commit(repo, "demo", commits[1], c2, child_helpers=False), [])
            self.assertEqual(c2.get("skip:child-helper"), 1)


class ContextTest(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.repo = make_repo(
            Path(self.td.name),
            [{"src/lib.aura": LIB0, "src/main.aura": MAIN0}, {"src/main.aura": MAIN1}, {"src/main.aura": MAIN2}],
        )
        self.commits = unm.list_commits(self.repo)

    def tearDown(self):
        self.td.cleanup()

    def test_cross_file_closure(self):
        c = self.commits[0]
        idx = ctxm.RepoIndex.build(self.repo, c.parent)
        self.assertEqual(idx.reachable("src/main.aura"), ["src/main.aura", "src/lib.aura"])
        u = unm.split_commit(self.repo, "demo", c, {})[0]
        ctx = ctxm.build_context(idx, u.file, u.name, u.old_form, u.old_body, u.new_body)
        self.assertIsNotNone(ctx.text)
        text = ctx.text
        # direct callee in full, the var it reads in full, never the repo load line
        self.assertIn("(define (h:clamp x)", text)
        self.assertIn("(define *limit* 10)", text)
        self.assertNotIn("(load ", text)
        self.assertNotIn("(require ", text)
        self.assertEqual(ctx.parts["std_requires_dropped"], ['(require "std/string" all:)'])
        self.assertIn("h:clamp", ctx.parts["cross_file"])
        self.assertEqual(ctx.parts["users"], ["m:user"])
        self.assertLess(text.index("(define *limit*"), text.index("(define (m:step x)"))

    def test_stub_depth_and_budget(self):
        c = self.commits[0]
        idx = ctxm.RepoIndex.build(self.repo, c.parent)
        body = "(lambda (x) (h:deep x))"
        ctx = ctxm.build_context(idx, "src/main.aura", "m:step", "(define (m:step x) (+ x 1))", "(lambda (x) (+ x 1))", body)
        self.assertIn("(define (h:deep y) (h:clamp y))", ctx.text)
        self.assertIn("(define h:clamp (lambda (x) #f))", ctx.text)
        tiny = ctxm.build_context(idx, "src/main.aura", "m:step", "(define (m:step x) (+ x 1))", "(lambda (x) (+ x 1))", body, budget=20)
        self.assertIsNone(tiny.text)
        self.assertEqual(tiny.reason, "context-too-long")

    def test_child_helpers(self):
        c = self.commits[1]
        cidx = ctxm.RepoIndex.build(self.repo, c.sha)
        pidx = ctxm.RepoIndex.build(self.repo, c.parent)
        added = set(cidx.defines("src/main.aura")) - set(pidx.defines("src/main.aura"))
        forms = ctxm.child_helper_forms(cidx, added, "(lambda (z) (m:new (m:step z)))", "m:user")
        self.assertEqual(list(forms), ["m:new"])


class IntentTest(unittest.TestCase):
    def test_violations(self):
        self.assertIn("auto-line", intm.violations("project(kv): controller gen → 146/148 (score-improved)"))
        self.assertIn("auto-line", intm.violations("smoke 148/148 load 2660"))
        self.assertIn("model-name", intm.violations("Use MiniMax-M3 to propose"))
        self.assertIn("cjk", intm.violations("Soft diverge 多发散"))
        self.assertIn("personal", intm.violations("High-diverge (user: more)"))
        self.assertEqual(intm.violations("Make pad:score-line! skip blank rows."), [])

    def test_template_is_deterministic_and_diff_based(self):
        old = "(lambda (xs) (map car xs))"
        new = "(lambda (xs k) (if (null? xs) k (pad:first (map car xs))))"
        a = intm.template_intent("pad:heads", old, new)
        self.assertEqual(a, intm.template_intent("pad:heads", old, new))
        self.assertIn("pad:heads", a)
        self.assertIn("k as a new parameter", a)
        self.assertIn("pad:first", a)
        self.assertIn("add 1 branch", a)
        self.assertEqual(intm.violations(a), [])

    def test_local_names_not_reported_as_calls(self):
        body = "(lambda (n) (let loop ((i 0) (acc 1)) (if (> i n) acc (loop (+ i 1) (pad:mul acc i)))))"
        calls = intm._calls(body)
        self.assertNotIn("loop", calls)
        self.assertIn("pad:mul", calls)

    def test_make_intent_without_llm(self):
        text, src, bad = intm.make_intent("f", "a.aura", "(lambda (x) x)", "(lambda (x) (g x))", None)
        self.assertEqual(src, "template")
        self.assertEqual(bad, [])
        self.assertTrue(text.startswith("Change f to"))

    def test_minimax_missing_config(self):
        self.assertIsNone(intm.load_minimax(Path("/nonexistent/minimax.env")))

    def test_sanitize(self):
        self.assertEqual(intm.sanitize("ask deepseek-v4 at /workspace/x"), "ask the model at /x")


def row(i: int, src: str, body: str, intent: str, group: str, t: int, name: str = "f", label: str = "KEEP") -> dict:
    return {
        "id": f"r{i}",
        "input": {"source": src, "intent": intent},
        "target": [
            {"kind": "query", "op": "find", "name": name},
            {"kind": "query", "op": "def-use", "name": name},
            {"kind": "synthesis", "op": "rebind", "name": name, "body": body, "summary": "s"},
        ],
        "verify": {"apply_ok": label == "KEEP", "label": label, "test": {"status": "none"}},
        "meta": {"repo": "demo", "file": "a.aura", "name": name, "commit_group": group, "commit_time": t, "old_body": "(lambda (x) x)", "label": label},
    }


class SplitTest(unittest.TestCase):
    def test_dedup_exact_near_conflict(self):
        long = "(define f (lambda (x) x))\n" + "(define pad:filler (lambda (a b c) (list a b c)))\n" * 20
        rows = [
            row(1, long, "(lambda (x) (+ x 1))", "add one", "g1", 1),
            row(2, long, "(lambda (x) (+ x 1))", "add one", "g2", 2),  # exact
            row(3, long + " ", "(lambda (x) (+ x 1))", "add one!", "g3", 3),  # near
            row(4, "(define f (lambda (x) x))", "(lambda (x) 1)", "same prompt", "g4", 4),
            row(5, "(define f (lambda (x) x))", "(lambda (x) 2)", "same prompt", "g5", 5),  # conflict
        ]
        drops = Counter()
        out = splm.dedup(rows, drops)
        self.assertEqual([r["id"] for r in out], ["r1"])
        self.assertEqual(drops, Counter({"exact-dup": 1, "near-dup": 1, "conflict": 2}))

    def test_caps(self):
        rows = [row(i, f"(define f{i} (lambda (x) x)) ;{'x' * i}", f"(lambda (x) {i})", f"i{i}", "g1", 1, name=f"f{i}") for i in range(12)]
        drops = Counter()
        out = splm.cap(rows, drops)
        self.assertLessEqual(len(out), splm.CAP_PER_COMMIT)

    def test_holdout_by_time_no_group_crossing(self):
        rows = [row(i, f"s{i}", "(lambda (x) x)", f"i{i}", f"g{i // 2}", i) for i in range(20)]
        split = splm.holdout(rows, 0.15)
        evals = sorted(g for g, s in split.items() if s == "eval")
        self.assertEqual(evals, ["g8", "g9"])  # the two newest of ten commit groups
        self.assertEqual(len(split), 10)


class ReportTest(unittest.TestCase):
    def test_scan_and_gates(self):
        rows = [row(i, f"(define f (lambda (x) x)) ;{i}", f"(lambda (x) {i})", f"Change f to return {i}.", f"g{i}", i) for i in range(3)]
        s = repm.scan_rows(rows)
        self.assertEqual(s["secret_rows"], 0)
        self.assertEqual(s["abs_path_rows"], 0)
        bad = row(9, '(define f (lambda (x) "/workspace/demo/x"))', "(lambda (x) x)", "api_key = '" + "sk-" + "abcdefghijklmnopqrstuv" + "'", "g9", 9)
        s2 = repm.scan_rows([bad])
        self.assertEqual(s2["secret_rows"], 1)
        self.assertEqual(s2["abs_path_rows"], 1)
        R = {
            "train": s, "eval": s, "all": s2, "train_labels": {"KEEP": 3}, "split_cross_groups": 0,
            "host": {"selftest": {"ok": True}, "bin_sha256": "x"},
            "rates": {"closure_failure": 0.1, "closure_failure_context": 0.0, "keep_tested_share": 0.5},
        }
        gates = repm.evaluate_gates(R)
        failed = {g["gate"] for g in gates if not g["ok"]}
        self.assertIn("secrets==0", failed)
        self.assertIn("abs-paths==0", failed)
        self.assertFalse(repm.gates_pass(gates))


class HostTest(unittest.TestCase):
    def test_refuses_unpinned_binary(self):
        with tempfile.TemporaryDirectory() as td:
            fake = Path(td) / "aura"
            fake.write_bytes(b"not aura")
            pin = {"aura_sha": "0" * 40, "bin_sha256": ["1" * 64], "bin_hints": []}
            with self.assertRaises(hostm.HostMismatch):
                hostm.resolve_host(aura_bin=str(fake), pin=pin)

    def test_refuses_wrong_source_sha(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "aura"
            (src / "build").mkdir(parents=True)
            (src / "lib" / "std").mkdir(parents=True)
            fake = src / "build" / "aura"
            fake.write_bytes(b"pinned bytes")
            git(src, "init", "-q")
            git(src, "commit", "-q", "--allow-empty", "-m", "x")
            pin = {"aura_sha": "0" * 40, "bin_sha256": [hostm.file_sha256(fake)], "bin_hints": []}
            with self.assertRaises(hostm.HostMismatch):
                hostm.resolve_host(aura_bin=str(fake), pin=pin)
            pin["aura_sha"] = git(src, "rev-parse", "HEAD").strip()
            host = hostm.resolve_host(aura_bin=str(fake), pin=pin)
            self.assertEqual(host.aura_sha, pin["aura_sha"])

    def test_pin_file_shape(self):
        pin = hostm.load_pin()
        self.assertEqual(len(pin["aura_sha"]), 40)
        self.assertTrue(all(len(x) == 64 for x in pin["bin_sha256"]))


class LabelLogicTest(unittest.TestCase):
    def test_regressed_compares_with_parent(self):
        base = labm.summarize_output("t", "T A OK\nT B OK\nX_TEST_OK\nerror: 1:1: unbound variable: loop\n", 1)
        same = labm.summarize_output("t", "T A OK\nT B OK\nX_TEST_OK\nerror: 1:1: unbound variable: loop\n", 1)
        worse = labm.summarize_output("t", "T A OK\nT B=1 WANT=2\n", 1)
        self.assertTrue(base.signal)
        self.assertFalse(labm.regressed(base, same))
        self.assertTrue(labm.regressed(base, worse))
        self.assertTrue(labm.regressed(base, labm.TestRun("t", "timeout", 90)))
        silent = labm.summarize_output("t", "nothing\n", 1)
        self.assertFalse(labm.regressed(silent, worse))

    def test_error_positions_do_not_count_as_regression(self):
        base = labm.summarize_output("t", "T A OK\nX_OK\nerror: 146:19: unbound variable: loop\n", 1)
        moved = labm.summarize_output("t", "T A OK\nX_OK\nerror: 151:19: unbound variable: loop\n", 1)
        self.assertFalse(labm.regressed(base, moved))

    def test_host_only_reject(self):
        from scripts.pipeline.run import host_only_reject

        repo = {"pad:lc-entry", "pad:x"}
        self.assertTrue(host_only_reject("arity mismatch: call 'string-append': expected 2", "arity", repo))
        self.assertTrue(host_only_reject("unbound variable: try; unbound variable: catch", "unbound", repo))
        self.assertFalse(host_only_reject("arity mismatch: call 'pad:lc-entry': expected 2", "arity", repo))
        self.assertFalse(host_only_reject("type error: argument 0", "type", repo))

    def test_splice(self):
        src = "(define (a) 1)\n(define (b) 2)\n"
        self.assertEqual(labm.splice(src, "(define (b) 2)", "(define (b) 3)", ["(define (c) 4)"]), "(define (a) 1)\n(define (c) 4)\n\n(define (b) 3)\n")
        self.assertIsNone(labm.splice(src, "(define (z) 0)", "x", []))

    def test_discover_tests(self):
        with tempfile.TemporaryDirectory() as td:
            repo = make_repo(Path(td), [{"src/lib.aura": LIB0, "src/main.aura": MAIN0, "src/main_test.aura": TEST0, "tests/test_net.aura": '(require "std/socket" all:)\n(load "src/main.aura")\n'}])
            sha = git(repo, "rev-parse", "HEAD").strip()
            got = labm.discover_tests(repo, sha, "src/main.aura", unm.ls_aura(repo, sha))
            self.assertEqual(got, ["src/main_test.aura"])
            self.assertEqual(labm.discover_tests(repo, sha, "src/lib.aura", unm.ls_aura(repo, sha)), [])

    def test_reject_category(self):
        self.assertEqual(labm.reject_category("['mutation-failed', 'unbound variable: x']"), "unbound")
        self.assertEqual(labm.reject_category("arity mismatch: call 'g'"), "arity")


def _host_or_none():
    try:
        return hostm.resolve_host()
    except (hostm.HostMismatch, OSError, KeyError):
        return None


HOST = _host_or_none()


def _host_runs() -> bool:
    if HOST is None:
        return False
    try:
        subprocess.run(
            [str(HOST.bin), "-e", "(+ 1 2)"], capture_output=True, timeout=30, check=True, env=os.environ | HOST.env()
        )
        return True
    except (OSError, subprocess.SubprocessError):
        return False


@unittest.skipUnless(_host_runs(), "pinned Aura host not available here")
class PinnedHostTest(unittest.TestCase):
    def test_selftest(self):
        self.assertTrue(hostm.selftest(HOST)["ok"])

    def test_strict_apply_identity_child_and_rollback(self):
        HOST.activate()
        ctx = "(define (g a b) (+ a b))\n(define (f x) (g x 1))\n"
        self.assertTrue(labm.load_check(ctx)[0])
        ok = labm.strict_apply(ctx, "f", "(lambda (x) (g x 1))", "(lambda (x) (g x 2))", "s")
        self.assertTrue(ok.ident_ok and ok.ok and not ok.prints_same)
        bad = labm.strict_apply(ctx, "f", "(lambda (x) (g x 1))", "(lambda (x) (g x))", "s")
        self.assertTrue(bad.ident_ok)
        self.assertFalse(bad.ok)
        self.assertEqual(bad.category, "arity")

    def test_load_check_catches_broken_context(self):
        HOST.activate()
        self.assertFalse(labm.load_check("(define *y* (undefined-fn 3))\n")[0])


if __name__ == "__main__":
    unittest.main()
