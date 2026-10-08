"""Extract top-level Aura defines as rebindable lambda bodies."""

from __future__ import annotations

import re
from typing import Iterator


def _skip_ws_comment(src: str, i: int) -> int:
    n = len(src)
    while i < n:
        while i < n and src[i] in " \t\r\n":
            i += 1
        if i < n and src[i] == ";":
            while i < n and src[i] != "\n":
                i += 1
            continue
        break
    return i


def _scan_form(src: str, start: int) -> int:
    """Return index after the top-level form starting at start ('(')."""
    n = len(src)
    depth = 0
    i = start
    in_str = False
    escape = False
    while i < n:
        ch = src[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            i += 1
            continue
        if ch == '"':
            in_str = True
            i += 1
            continue
        if ch == ";":
            while i < n and src[i] != "\n":
                i += 1
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            i += 1
            if depth == 0:
                return i
            continue
        i += 1
    return n


def iter_top_forms(src: str) -> Iterator[str]:
    i = 0
    n = len(src)
    while i < n:
        i = _skip_ws_comment(src, i)
        if i >= n:
            break
        if src[i] != "(":
            i += 1
            continue
        end = _scan_form(src, i)
        yield src[i:end]
        i = end


_DEFINE_SUGAR = re.compile(
    r"^\(define\s+\(([^\s()]+)((?:\s+[^\s()]+)*)\)\s*",
    re.S,
)
_DEFINE_LAMBDA = re.compile(
    r"^\(define\s+([^\s()]+)\s+(\(lambda\b)",
    re.S,
)


def _inner_of_define(form: str, header_end: int) -> str:
    body = form[header_end:].rstrip()
    if body.endswith(")"):
        body = body[:-1].strip()
    return body


def sugar_to_lambda(params: str, inner: str) -> str:
    params = " ".join(params.split())
    return f"(lambda ({params}) {inner})" if params else f"(lambda () {inner})"


def extract_defines(src: str) -> dict[str, str]:
    """Map define name → one (lambda …) body string. Last def wins."""
    out: dict[str, str] = {}
    for form in iter_top_forms(src):
        m = _DEFINE_SUGAR.match(form)
        if m:
            name = m.group(1)
            params = m.group(2)
            inner = _inner_of_define(form, m.end())
            if inner:
                out[name] = sugar_to_lambda(params, inner)
            continue
        m = _DEFINE_LAMBDA.match(form)
        if m:
            name = m.group(1)
            inner = _inner_of_define(form, m.start(2))
            if inner.startswith("(lambda"):
                out[name] = inner
    return out


def patch_for(name: str, body: str, summary: str) -> list[dict]:
    return [
        {"kind": "query", "op": "find", "name": name},
        {"kind": "query", "op": "def-use", "name": name},
        {
            "kind": "synthesis",
            "op": "rebind",
            "name": name,
            "body": body,
            "summary": summary,
        },
    ]


# Focused collect prompts and the export length gate share this budget.
# A whole business file is larger; a define plus its neighbors stays under it.
MAX_FOCUS_CHARS = 12000

_DELIM = set(" \t\r\n()[]{}\"'`;|,")


def _skip_string(src: str, i: int) -> int:
    n = len(src)
    i += 1
    esc = False
    while i < n:
        ch = src[i]
        if esc:
            esc = False
        elif ch == "\\":
            esc = True
        elif ch == '"':
            return i + 1
        i += 1
    return n


def _skip_comment(src: str, i: int) -> int:
    n = len(src)
    if src.startswith("#|", i):
        end = src.find("|#", i + 2)
        return n if end < 0 else end + 2
    if src[i] == ";":
        end = src.find("\n", i)
        return n if end < 0 else end
    return i


def code_symbols(src: str) -> set[str]:
    """Symbols outside strings and comments. `#\\` character names are skipped."""
    found: set[str] = set()
    i = 0
    n = len(src)
    while i < n:
        ch = src[i]
        if ch in " \t\r\n":
            i += 1
            continue
        if ch == ";" or src.startswith("#|", i):
            i = _skip_comment(src, i)
            continue
        if ch == '"':
            i = _skip_string(src, i)
            continue
        if src.startswith("#\\", i):
            i += 2
            while i < n and src[i] not in _DELIM:
                i += 1
            continue
        if ch in _DELIM:
            i += 1
            continue
        j = i + 1
        while j < n and src[j] not in _DELIM:
            j += 1
        found.add(src[i:j])
        i = j
    return found


def strip_comments(src: str) -> str:
    out: list[str] = []
    i = 0
    n = len(src)
    while i < n:
        ch = src[i]
        if ch == ";" or src.startswith("#|", i):
            i = _skip_comment(src, i)
            out.append(" ")
            continue
        if ch == '"':
            j = _skip_string(src, i)
            out.append(src[i:j])
            i = j
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def bodies_equivalent(a: str, b: str) -> bool:
    return " ".join(strip_comments(a).split()) == " ".join(strip_comments(b).split())


def paren_balanced(src: str) -> bool:
    depth = 0
    i = 0
    n = len(src)
    while i < n:
        ch = src[i]
        if ch == ";" or src.startswith("#|", i):
            i = _skip_comment(src, i)
            continue
        if ch == '"':
            i = _skip_string(src, i)
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth < 0:
                return False
        i += 1
    return depth == 0


def lambda_params(body: str) -> set[str]:
    m = re.match(r"^\(\s*lambda\s+(\([^)]*\)|[^\s()]+)", body.strip())
    if not m:
        return set()
    raw = m.group(1)
    names = raw[1:-1].split() if raw.startswith("(") else [raw]
    return {n for n in names if n != "."}


def lambda_param_form(body: str) -> str:
    m = re.match(r"^\(\s*lambda\s+(\([^)]*\)|[^\s()]+)", body.strip())
    if not m:
        return "()"
    raw = m.group(1)
    return raw if raw.startswith("(") else f"({raw})"


def focused_source(src: str, name: str) -> str | None:
    """Target define, full def-use neighbors, and callee signatures only.

    Neighbors are dropped from the end until the excerpt fits MAX_FOCUS_CHARS.
    Returns None when the target define alone does not fit.
    """
    defs = extract_defines(src)
    body = defs.get(name)
    if not body:
        return None
    syms = code_symbols(body)
    params = lambda_params(body)
    users: list[str] = []
    callees: list[str] = []
    for other, obody in defs.items():
        if other == name:
            continue
        if name in code_symbols(obody):
            users.append(other)
        elif other in syms and other not in params:
            callees.append(other)
    parts = [f"(define {name} {body})"]
    seen = {name}
    for other in users:
        form = f"(define {other} {defs[other]})"
        if len(form) > 2500:
            form = f"(define {other} (lambda {lambda_param_form(defs[other])} #f))"
        parts.append(form)
        seen.add(other)
    for other in callees:
        if other in seen:
            continue
        parts.append(f"(define {other} (lambda {lambda_param_form(defs[other])} #f))")
        seen.add(other)
    while len("\n".join(parts)) > MAX_FOCUS_CHARS and len(parts) > 1:
        parts.pop()
    text = "\n".join(parts)
    if len(text) > MAX_FOCUS_CHARS:
        return None
    return text + "\n"
