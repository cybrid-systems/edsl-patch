import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from synth import candidates, judge, leaks_name, parse_array, probe_program, task_prompt

SRC = (
    "(define *k* 3)\n"
    "(define (g x) (+ x *k*))\n"
    "(define (h y) (* y 2))\n"
    "(define (f x) (let ((a (g x))) (h (+ a a a a a a a a a a a a a a a a a a a a a a a a a a a a a a a))))\n"
)


class Synth(unittest.TestCase):
    def setUp(self):
        self.cands = candidates([{"id": "r", "input": {"source": SRC}}], 20, 2000)

    def test_candidates_gold_callees_are_functions_only(self):
        c = [c for c in self.cands if c["name"] == "f"][0]
        self.assertEqual(c["callees"], ["g", "h"])

    def test_fill_prompt_has_hole(self):
        c = [c for c in self.cands if c["name"] == "f"][0]
        src, intent = task_prompt("fill", c, "adds things")
        self.assertIn("(define f (lambda (x) #f))", src)
        self.assertIn("(define (g x)", src)
        self.assertIn("Implement f", intent)

    def test_judge_offline_rejections(self):
        c = [c for c in self.cands if c["name"] == "f"][0]
        q = [{"kind": "query", "op": "find", "name": "f"}]
        reb = {"kind": "synthesis", "op": "rebind", "name": "f", "body": c["body"], "summary": "s"}
        v = judge("deps", c, q + [{"kind": "query", "op": "def-use", "name": "g"}, reb], SRC, 5)
        self.assertEqual(v["reason"], "deps-mismatch")
        wrong = dict(reb, name="g")
        v = judge("locate", c, [{"kind": "query", "op": "find", "name": "g"}, wrong], SRC, 5)
        self.assertEqual(v["reason"], "wrong-target")
        v = judge("locate", c, [{"op": "find", "name": "f"}, reb], SRC, 5)
        self.assertFalse(v["schema_ok"])
        v = judge("locate", c, q + [dict(reb, body="(lambda (x) (g x))")], SRC, 5)
        self.assertEqual(v["reason"], "body-changed")

    def test_probe_program_calls_and_watch(self):
        prog = probe_program("(define (f a b) a)", "f", 2, "int", ["*k*"])
        self.assertIn('(display (try (f 0 1) (catch (e) "ERR")))', prog)
        self.assertIn('(display "@@0 *k*=") (display *k*)', prog)

    def test_parse_and_leak(self):
        self.assertEqual(parse_array('```json\n[{"a":1}]\n```'), [{"a": 1}])
        self.assertTrue(leaks_name("calls pad:f! here", "pad:f!"))
        self.assertFalse(leaks_name("calls pad:f!x here", "pad:f!"))


if __name__ == "__main__":
    unittest.main()
