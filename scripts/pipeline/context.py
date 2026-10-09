"""Stage 3: closed dependency context at the parent commit.

The prompt context is the target define plus what it needs to load and
typecheck on the pinned host:

  * `(require "std/...")` lines of every file that contributes a full form
  * file-level vars referenced (transitively; vars run at load time)
  * direct callees as full forms (deeper callees as arity stubs)
  * cross-file helpers, found through the load/require graph first and
    then anywhere in the repo at the parent commit
  * helpers that the same commit introduces (child-only), when allowed
  * up to two def-use neighbors (callers) of the target

Repo `load`/`require` lines are never kept: the excerpt must not depend on
a sibling worktree. Rows that cannot be closed are reported with a reason,
not silently dropped.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from parse_aura import MAX_FOCUS_CHARS, code_symbols, lambda_params

from .units import Form, define_map, is_harness, ls_aura, show, top_forms

FULL_FN_MAX = 2500
FULL_VAR_MAX = 3000
USER_MAX = 1500
MAX_USERS = 2
_STR = re.compile(r'^\((?:require|load)\s+"([^"]+)"')


def _path_arg(form: Form) -> str:
    m = _STR.match(form.text)
    return m.group(1) if m else ""


@dataclass
class RepoIndex:
    """All non-harness top-level forms of one repo at one commit."""

    repo: Path
    sha: str
    files: dict[str, list[Form]] = field(default_factory=dict)

    @classmethod
    def build(cls, repo: Path, sha: str) -> "RepoIndex":
        idx = cls(repo=repo, sha=sha)
        for rel in ls_aura(repo, sha):
            if is_harness(rel):
                continue
            src = show(repo, sha, rel)
            if src is None or len(src) > 400_000:
                continue
            idx.files[rel] = top_forms(src)
        return idx

    def defines(self, rel: str) -> dict[str, Form]:
        return {f.name: f for f in self.files.get(rel, []) if f.kind in ("define-fn", "define-var")}

    def resolve_path(self, arg: str) -> str | None:
        """Map a load/require argument to a repo-relative file at this commit."""
        if not arg or arg.startswith("std/"):
            return None
        cand = arg.lstrip("./")
        if not cand.endswith(".aura"):
            cand += ".aura"
        if cand in self.files:
            return cand
        parts = cand.split("/")
        for k in range(1, len(parts)):
            tail = "/".join(parts[k:])
            hits = [f for f in self.files if f == tail or f.endswith("/" + tail)]
            if len(hits) == 1:
                return hits[0]
        return None

    def reachable(self, rel: str) -> list[str]:
        """rel first, then files it loads/requires (breadth first)."""
        order, queue = [], [rel]
        while queue:
            cur = queue.pop(0)
            if cur in order or cur not in self.files:
                continue
            order.append(cur)
            for f in self.files[cur]:
                if f.kind in ("load", "require"):
                    nxt = self.resolve_path(_path_arg(f))
                    if nxt and nxt not in order:
                        queue.append(nxt)
        return order

    def std_requires(self, rel: str) -> list[str]:
        return [f.text for f in self.files.get(rel, []) if f.kind == "require" and _path_arg(f).startswith("std/")]


def free_symbols(form_text: str, params: str = "") -> set[str]:
    syms = code_symbols(form_text)
    syms -= set(params.strip("()").split())
    return {s for s in syms if not re.match(r"^[-+]?[\d.]+$", s) and not s.startswith(("#", ":", "'"))}


def stub(form: Form) -> str:
    if form.kind == "define-var":
        return f"(define {form.name} #f)"
    return f"(define {form.name} (lambda {form.params} #f))"


@dataclass
class Context:
    text: str | None
    reason: str = ""
    parts: dict = field(default_factory=dict)


class Resolver:
    def __init__(self, idx: RepoIndex, rel: str):
        self.idx = idx
        self.rel = rel
        self.reach = idx.reachable(rel)
        self._maps = {f: idx.defines(f) for f in self.reach}
        self._global: dict[str, tuple[str, Form]] = {}
        for f in sorted(idx.files):
            for name, form in idx.defines(f).items():
                self._global.setdefault(name, (f, form))

    def lookup(self, sym: str) -> tuple[str, Form, bool] | None:
        """(file, form, reached-through-load-graph)"""
        for f in self.reach:
            form = self._maps[f].get(sym)
            if form is not None:
                return f, form, True
        hit = self._global.get(sym)
        if hit:
            return hit[0], hit[1], False
        return None


def build_context(
    idx: RepoIndex,
    rel: str,
    name: str,
    old_form: str,
    old_body: str,
    new_body: str,
    child_helpers: dict[str, Form] | None = None,
    budget: int = MAX_FOCUS_CHARS,
    keep_requires: bool = False,
) -> Context:
    res = Resolver(idx, rel)
    child_helpers = child_helpers or {}
    target_params = " ".join(lambda_params(old_body) | lambda_params(new_body))
    # sym -> (file, Form, depth, full?)
    chosen: dict[str, dict] = {}
    unresolved: set[str] = set()
    cross_file: set[str] = set()
    off_graph: set[str] = set()
    queue: list[tuple[str, int]] = []

    def need(text: str, params: str, depth: int) -> None:
        for s in sorted(free_symbols(text, params)):
            if s != name:
                queue.append((s, depth))

    need(old_body, target_params, 1)
    need(new_body, target_params, 1)

    helper_forms: list[Form] = []
    for hname, hform in child_helpers.items():
        helper_forms.append(hform)
        chosen[hname] = {"file": "(child)", "form": hform, "depth": 1, "full": True, "helper": True}
        need(hform.text, hform.params, 2)

    users: list[tuple[str, Form]] = []
    for f in res.reach[:1]:
        for oname, oform in res._maps[f].items():
            if oname != name and oform.kind == "define-fn" and name in code_symbols(oform.body):
                users.append((f, oform))
    users = users[:MAX_USERS]
    user_full = [len(u.text) <= USER_MAX for _, u in users]
    for (f, u), full in zip(users, user_full):
        if full:
            need(u.text, u.params, 2)

    while queue:
        sym, depth = queue.pop(0)
        if sym in chosen or sym in unresolved or any(u.name == sym for _, u in users):
            continue
        hit = res.lookup(sym)
        if hit is None:
            unresolved.add(sym)
            continue
        f, form, reached = hit
        if f != rel:
            cross_file.add(sym)
        if not reached:
            off_graph.add(sym)
        if form.kind == "define-var":
            full = len(form.text) <= FULL_VAR_MAX
        else:
            full = depth <= 1 and len(form.text) <= FULL_FN_MAX
        chosen[sym] = {"file": f, "form": form, "depth": depth, "full": full}
        if full:
            need(form.text, form.params, depth + 1)

    def var_order() -> list[str]:
        vars_ = [s for s, c in chosen.items() if c["form"].kind == "define-var"]
        seen: set[str] = set()
        out: list[str] = []

        def visit(s: str) -> None:
            if s in seen:
                return
            seen.add(s)
            c = chosen[s]
            if c["full"]:
                for d in sorted(free_symbols(c["form"].text)):
                    if d in chosen and chosen[d]["form"].kind == "define-var" and d != s:
                        visit(d)
            out.append(s)

        for s in sorted(vars_, key=lambda v: (chosen[v]["file"], chosen[v]["form"].start)):
            visit(s)
        return out

    def std_reqs() -> list[str]:
        files = {rel} | {c["file"] for c in chosen.values() if c["full"] and c["file"] != "(child)"}
        reqs: list[str] = []
        for f in sorted(files, key=lambda x: (x != rel, x)):
            for r in idx.std_requires(f):
                if r not in reqs:
                    reqs.append(r)
        return reqs

    def render() -> str:
        # `require`/`load` forms are not emitted: the post-mutate typecheck on the
        # pinned host reads them as unbound calls, and std exports resolve without them.
        reqs = std_reqs() if keep_requires else []
        fns = [
            s for s, c in chosen.items() if c["form"].kind == "define-fn" and not c.get("helper")
        ]
        lines = list(reqs)
        lines += [chosen[s]["form"].text if chosen[s]["full"] else stub(chosen[s]["form"]) for s in fns]
        lines += [chosen[s]["form"].text if chosen[s]["full"] else stub(chosen[s]["form"]) for s in var_order()]
        lines += [h.text for h in helper_forms]
        lines.append(old_form)
        for (f, u), full in zip(users, user_full):
            lines.append(u.text if full else stub(u))
        return "\n".join(lines) + "\n"

    text = render()
    steps = 0
    while len(text) > budget and steps < 4:
        steps += 1
        if steps == 1:
            user_full = [False] * len(users)
        elif steps == 2:
            for c in chosen.values():
                if c["form"].kind == "define-fn" and not c.get("helper"):
                    c["full"] = False
        elif steps == 3:
            users = []
            user_full = []
        else:
            for c in chosen.values():
                if c["form"].kind == "define-var" and len(c["form"].text) > 400:
                    c["full"] = False
        text = render()
    parts = {
        "full": sorted(s for s, c in chosen.items() if c["full"] and not c.get("helper")),
        "stub": sorted(s for s, c in chosen.items() if not c["full"]),
        "child_helpers": sorted(child_helpers),
        "users": [u.name for _, u in users],
        "cross_file": sorted(cross_file),
        "off_graph": sorted(off_graph),
        "unresolved": len(unresolved),
        "std_requires_dropped": [] if keep_requires else std_reqs(),
        "degrade_steps": steps,
        "chars": len(text),
    }
    if len(text) > budget:
        return Context(None, "context-too-long", parts)
    return Context(text, "", parts)


def child_helper_forms(idx_child: RepoIndex, added: set[str], body: str, name: str) -> dict[str, Form]:
    """Child-only defines the new body needs, transitively among themselves."""
    out: dict[str, Form] = {}
    glob = {}
    for f in sorted(idx_child.files):
        for n, form in idx_child.defines(f).items():
            glob.setdefault(n, form)
    queue = sorted((code_symbols(body) - {name}) & added)
    while queue:
        s = queue.pop(0)
        if s in out or s not in glob:
            continue
        out[s] = glob[s]
        queue += sorted((code_symbols(glob[s].text) - {s, name}) & added)
    return out
