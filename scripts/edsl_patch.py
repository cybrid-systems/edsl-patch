"""Shared patch contract: legal check, Scheme escaping, Aura driver emit."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

QUERY_OPS = ("find", "def-use", "root")
SYNTHESIS_OPS = ("rebind", "fill")
REFUSE_OPS = ("frozen", "capability", "schema")
REFUSE_FIELDS = ("kind", "op", "name", "why")

QUERY_FIELDS = {
    "find": ("kind", "op", "name"),
    "def-use": ("kind", "op", "name"),
    "root": ("kind", "op"),
}
SYNTHESIS_FIELDS = {
    "rebind": ("kind", "op", "name", "body", "summary"),
    "fill": ("kind", "op", "template", "args"),
}

ILLEGAL_HINTS = (
    "eval",
    "synthesize:define",
    "fiber:spawn",
    "c-load",
    "<think>",
    "```",
)

SYSTEM_CONTRACT = """You emit Aura EDSL patches as a JSON array. No markdown, no <think>.
Sequence: one or more query ops, then exactly one completion: synthesis rebind OR refuse.
Query ops: find (name), def-use (name), root. Name-based only; never node ids.
Synthesis: rebind (name, body, summary) with name in observe.hot, never in observe.frozen.
Refuse: {"kind":"refuse","op":"frozen|capability|schema","name":"…","why":"…"}.
rebind.body is one (lambda …) form. Two-arm if when if is used. No extra define.
Illegal: eval, c-load, extra defines, fiber:spawn, synthesize:define, skip, persist, restore, yield.
"""


class PatchError(ValueError):
    pass


def scheme_string(s: str) -> str:
    out = ['"']
    for ch in s:
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def _require_keys(obj: dict[str, Any], allowed: tuple[str, ...], where: str) -> None:
    extra = set(obj) - set(allowed)
    if extra:
        raise PatchError(f"{where}: extra keys {sorted(extra)}")
    missing = [k for k in allowed if k not in obj]
    if missing:
        raise PatchError(f"{where}: missing keys {missing}")


def _check_name(name: Any, where: str) -> None:
    if not isinstance(name, str) or not name or any(c.isspace() for c in name):
        raise PatchError(f"{where}: name must be a non-empty token")


def _check_body(body: Any, where: str) -> None:
    if not isinstance(body, str) or not body.strip():
        raise PatchError(f"{where}: body must be a non-empty string")
    text = body.strip()
    low = text.lower()
    if not text.startswith("(lambda"):
        raise PatchError(f"{where}: body must be one (lambda …) form")
    if "(define " in text:
        raise PatchError(f"{where}: body must not contain extra define")
    for hint in ILLEGAL_HINTS:
        if hint in low or hint in text:
            raise PatchError(f"{where}: illegal token {hint!r}")


def validate_patch(patch: Any, observe: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    if not isinstance(patch, list) or not patch:
        raise PatchError("patch must be a non-empty JSON array")
    kinds = []
    for i, step in enumerate(patch):
        if not isinstance(step, dict):
            raise PatchError(f"step {i}: must be an object")
        kind = step.get("kind")
        op = step.get("op")
        if kind == "query":
            if op not in QUERY_OPS:
                raise PatchError(f"step {i}: illegal query op {op!r}")
            _require_keys(step, QUERY_FIELDS[op], f"step {i}")
            if op != "root":
                _check_name(step["name"], f"step {i}")
        elif kind == "synthesis":
            if op not in SYNTHESIS_OPS:
                raise PatchError(f"step {i}: illegal synthesis op {op!r}")
            _require_keys(step, SYNTHESIS_FIELDS[op], f"step {i}")
            if op == "rebind":
                _check_name(step["name"], f"step {i}")
                _check_body(step["body"], f"step {i}")
                if not isinstance(step["summary"], str) or not step["summary"]:
                    raise PatchError(f"step {i}: summary must be a non-empty string")
            else:
                if not isinstance(step["template"], str) or not step["template"]:
                    raise PatchError(f"step {i}: template must be a non-empty string")
                args = step["args"]
                if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
                    raise PatchError(f"step {i}: args must be a list of strings")
        elif kind == "refuse":
            if op not in REFUSE_OPS:
                raise PatchError(f"step {i}: illegal refuse op {op!r}")
            _require_keys(step, REFUSE_FIELDS, f"step {i}")
            _check_name(step["name"], f"step {i}")
            if not isinstance(step["why"], str) or not step["why"].strip():
                raise PatchError(f"step {i}: why must be a non-empty string")
        else:
            raise PatchError(f"step {i}: illegal kind {kind!r}")
        kinds.append(kind)
    if "query" not in kinds:
        raise PatchError("at least one query step")
    n_syn = kinds.count("synthesis")
    n_ref = kinds.count("refuse")
    if n_syn + n_ref != 1:
        raise PatchError("exactly one synthesis or refuse completion")
    if kinds[-1] not in ("synthesis", "refuse"):
        raise PatchError("last step must be synthesis or refuse")
    if any(k != "query" for k in kinds[:-1]):
        raise PatchError("all steps before completion must be query")
    last = patch[-1]
    if last["kind"] == "synthesis" and last["op"] == "rebind":
        finds = [
            s for s in patch[:-1] if s.get("op") == "find" and s.get("name") == last["name"]
        ]
        if not finds:
            raise PatchError("rebind requires a prior find of the same name")
        if observe:
            frozen = list(observe.get("frozen") or [])
            hot = observe.get("hot")
            if last["name"] in frozen:
                raise PatchError(f"rebind of frozen name {last['name']!r}")
            if isinstance(hot, list) and last["name"] not in hot:
                raise PatchError(f"rebind name {last['name']!r} not in observe.hot")
    return patch


def load_patch(path: str | Path) -> list[dict[str, Any]]:
    raw = Path(path).read_text(encoding="utf-8")
    data = json.loads(raw)
    if isinstance(data, dict) and "target" in data:
        data = data["target"]
    return validate_patch(data)


def load_sample(obj: dict[str, Any] | str | Path) -> dict[str, Any]:
    if not isinstance(obj, dict):
        text = Path(obj).read_text(encoding="utf-8").splitlines()[0]
        obj = json.loads(text)
    if not isinstance(obj, dict):
        raise PatchError("sample must be a JSON object")
    source = obj.get("input", {}).get("source") if isinstance(obj.get("input"), dict) else None
    if not isinstance(source, str) or not source.strip():
        raise PatchError("sample.input.source must be a non-empty string")
    observe = obj.get("input", {}).get("observe") if isinstance(obj.get("input"), dict) else None
    if observe is not None and not isinstance(observe, dict):
        observe = None
    inp = dict(obj.get("input") or {})
    inp["source"] = source
    if obj.get("sft") is False:
        return obj | {"input": inp, "target": obj.get("target") or []}
    target = validate_patch(obj.get("target"), observe=observe)
    return obj | {"input": inp, "target": target}


def normalize_source(src: str) -> str:
    return " ".join(src.split())


def sources_match(got: str, expected: str) -> bool:
    return normalize_source(got) == normalize_source(expected)


def emit_driver(source_path: Path, patch: list[dict[str, Any]]) -> str:
    """Aura program: load source, run query*, synthesize, print one JSON line."""
    lines = [
        ";; generated by scripts/apply.py — do not edit",
        f"(load {scheme_string(str(source_path))})",
        "(define *ok* #t)",
        "(define *q* '())",
        "(define *syn-ok* #f)",
        "(define *syn-op* \"\")",
        "",
        "(define (q-empty? v)",
        "  (or (null? v) (eq? v #f)))",
        "",
        "(define (q-run op val)",
        "  (let ((empty (q-empty? val))",
        "        (ok (not (eq? val #f))))",
        "    (if (not ok) (set! *ok* #f) #f)",
        "    (if (and (string=? op \"find\") empty) (set! *ok* #f) #f)",
        "    (set! *q* (cons (hash \"op\" op \"ok\" ok \"empty\" empty) *q*))",
        "    ok))",
        "",
    ]
    for step in patch:
        if step["kind"] != "query":
            continue
        op = step["op"]
        if op == "root":
            lines.append(
                '(q-run "root" (try (query :root) (catch (e) #f)))'
            )
        elif op == "find":
            lines.append(
                f'(q-run "find" (try (query :find {scheme_string(step["name"])})'
                f" (catch (e) #f)))"
            )
        elif op == "def-use":
            lines.append(
                f'(q-run "def-use" (try (query :def-use {scheme_string(step["name"])})'
                f" (catch (e) #f)))"
            )
    synth = patch[-1] if patch else {"kind": "refuse", "op": "schema"}
    lines += [
        "",
        '(define *snap* (try (ast:snapshot "edsl-patch") (catch (e) -1)))',
        "",
    ]
    if synth.get("kind") == "refuse":
        lines += [
            '(set! *syn-op* "refuse")',
            "(set! *syn-ok* #t)",
        ]
    elif synth.get("op") == "rebind":
        lines += [
            f"(set! *syn-op* \"rebind\")",
            f"(set! *syn-ok* (try (mutate:rebind {scheme_string(synth['name'])} "
            f"{scheme_string(synth['body'])} {scheme_string(synth['summary'])}) "
            f"(catch (e) #f)))",
        ]
    else:
        args = " ".join(scheme_string(a) for a in synth["args"])
        fill = f"(synthesize:fill {scheme_string(synth['template'])}" + (
            f" {args}" if args else ""
        ) + ")"
        lines += [
            f"(set! *syn-op* \"fill\")",
            f"(set! *syn-ok* (try {fill} (catch (e) #f)))",
        ]
    lines += [
        "(if (not *syn-ok*) (set! *ok* #f) #f)",
        "(define *eval-ok* (try (begin (eval-current) #t) (catch (e) #f)))",
        "(if (not *eval-ok*)",
        "  (begin",
        "    (set! *ok* #f)",
        "    (if (and (number? *snap*) (>= *snap* 0))",
        "      (try (ast:restore *snap*) (catch (e) #f))",
        "      #f))",
        "  #f)",
        "(define *src* (try (current-source :workspace) (catch (e) \"\")))",
        "(define *out*",
        "  (hash \"ok\" *ok*",
        '        "query" *q*',
        '        "synthesis" (hash "op" *syn-op* "ok" *syn-ok*)',
        '        "source" *src*))',
        '(display "EDSL_PATCH_RESULT ")',
        "(display (json-encode *out*))",
        "(newline)",
    ]
    return "\n".join(lines) + "\n"


def render_define(name: str, params: str, inner: str, sugar: bool) -> str:
    if sugar:
        return f"(define ({name} {params}) {inner})"
    return f"(define {name} (lambda ({params}) {inner}))"


def render_source(lesson: dict[str, Any]) -> str:
    helpers = str(lesson.get("helpers") or "").strip()
    defn = render_define(
        str(lesson["name"]),
        str(lesson["params"]),
        str(lesson["inner0"]),
        bool(lesson.get("sugar")),
    )
    if helpers:
        return helpers + "\n" + defn
    return defn


def lesson_body(lesson: dict[str, Any]) -> str:
    return f"(lambda ({lesson['params']}) {lesson['inner1']})"


def lesson_to_sample(lesson: dict[str, Any]) -> dict[str, Any]:
    name = lesson["name"]
    body = lesson_body(lesson)
    target = [
        {"kind": "query", "op": "find", "name": name},
        {"kind": "query", "op": "def-use", "name": name},
        {
            "kind": "synthesis",
            "op": "rebind",
            "name": name,
            "body": body,
            "summary": lesson["summary"],
        },
    ]
    validate_patch(target)
    return {
        "id": lesson["id"],
        "input": {"source": render_source(lesson)},
        "target": target,
        "verify": {"apply_ok": True},
    }


def aura_hash(obj: dict[str, Any]) -> str:
    parts = []
    for k, v in obj.items():
        if isinstance(v, bool):
            lit = "#t" if v else "#f"
        elif isinstance(v, (int, float)) and not isinstance(v, bool):
            lit = str(v)
        else:
            lit = scheme_string(str(v))
        parts.append(f"{scheme_string(str(k))} {lit}")
    return "(hash " + " ".join(parts) + ")"

