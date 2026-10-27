import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from export_sft import clean_intent, dedupe_context, difficulty, sample_weight, to_sft


def _row(intent, source, test_status=None, queries=("find", "def-use")):
    target = [{"kind": "query", "op": q, "name": "f"} for q in queries]
    target.append({"kind": "synthesis", "op": "rebind", "name": "f", "body": "(lambda (x) (g x))", "summary": "s"})
    row = {"input": {"source": source, "intent": intent}, "target": target}
    if test_status:
        row["verify"] = {"test": {"status": test_status}}
    return row


SRC = "(define (g x) x)\n(define (f x) (g x))\n(define (g x) x)\n(define (h y) (f y))\n"


class ExportLabels(unittest.TestCase):
    def test_dedupe_identical_define(self):
        out = dedupe_context(SRC)
        self.assertEqual(out.count("(define (g x) x)"), 1)
        self.assertIn("(define (h y) (f y))", out)

    def test_dedupe_keeps_differing_redefine(self):
        src = "(define a 1)\n(define a 2)\n"
        self.assertEqual(dedupe_context(src), src)

    def test_clean_intent(self):
        self.assertEqual(clean_intent("Make `f` call **g**  now"), "Make f call g now")

    def test_prompt_uses_clean_context(self):
        user = to_sft(_row("Make `f` use g", SRC))["messages"][1]["content"]
        self.assertEqual(user.count("(define (g x) x)"), 1)
        self.assertNotIn("`", user)

    def test_trivial_when_named_and_self_queries(self):
        d = difficulty(_row("Make f use g", SRC))
        self.assertTrue(d["target_given"])
        self.assertTrue(d["trivial"])
        self.assertEqual(d["defuse_span"], 2)  # g (callee) + h (caller)
        self.assertEqual(d["query_steps"], 2)

    def test_not_trivial_when_unnamed(self):
        d = difficulty(_row("Route the value through the identity helper", SRC))
        self.assertFalse(d["trivial"])
        self.assertEqual(d["tier"], "easy")

    def test_weights(self):
        self.assertEqual(sample_weight(_row("other words", SRC, "pass")), 1.0)
        self.assertEqual(sample_weight(_row("other words", SRC, "none")), 0.5)
        self.assertEqual(sample_weight(_row("fix f", SRC, "none")), 0.25)
        self.assertEqual(sample_weight(_row("other words", SRC)), 1.0)  # legacy rows: no test stage


if __name__ == "__main__":
    unittest.main()
