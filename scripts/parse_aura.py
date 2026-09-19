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
