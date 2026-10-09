"""Stages 1-2: pick commits, split each commit into per-define units."""

from __future__ import annotations

import hashlib
import re
import subprocess
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from parse_aura import _scan_form, _skip_ws_comment, bodies_equivalent, code_symbols, paren_balanced, strip_comments

# Test drivers, case tables, smokes and fixtures are harness code, not units.
_HARNESS = re.compile(r"(^|/)(tests?|fixtures)/|(^|[/_])test_|_test\.aura$|_cases\.aura$|smoke|_wire\.aura$")
MAX_FILE_CHARS = 200_000
_META_NAME = re.compile(r"stamp-info|stamp-system|self_evolve_stamp|traj[-_]id|build-info|version-info", re.I)
_META_TOKEN = re.compile(r'^"?(?:[0-9a-f]{7,40}|\d{4}-\d\d-\d\d[T ]?[\d:.Z+-]*|v?\d+\.\d+(?:\.\d+)?)"?$', re.I)


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True, stderr=subprocess.DEVNULL)


@lru_cache(maxsize=4096)
def _show(repo: str, sha: str, rel: str) -> str | None:
    try:
        return subprocess.check_output(
            ["git", "-C", repo, "show", f"{sha}:{rel}"], stderr=subprocess.DEVNULL
        ).decode("utf-8")
    except (subprocess.CalledProcessError, UnicodeDecodeError):
        return None


def show(repo: Path, sha: str, rel: str) -> str | None:
    return _show(str(repo), sha, rel)


@lru_cache(maxsize=512)
def _ls_aura(repo: str, sha: str) -> tuple[str, ...]:
    out = subprocess.check_output(["git", "-C", repo, "ls-tree", "-r", "--name-only", sha], text=True)
    return tuple(p for p in out.split("\n") if p.endswith(".aura"))


def ls_aura(repo: Path, sha: str) -> tuple[str, ...]:
    return _ls_aura(str(repo), sha)


def is_harness(rel: str) -> bool:
    return bool(_HARNESS.search(rel))


@dataclass
class Form:
    """One top-level form with its span in the file."""

    text: str
    start: int
    end: int
    kind: str  # define-fn | define-var | require | load | export | other
    name: str = ""
    body: str = ""  # (lambda ...) for define-fn, init expr for define-var
    params: str = "()"


_SUGAR = re.compile(r"^\(define\s+\(([^\s()]+)((?:\s+[^\s()]+)*)\s*\)", re.S)
_NAMED = re.compile(r"^\(define\s+([^\s()]+)\s+", re.S)


def _close(form: str, header_end: int) -> str:
    inner = form[header_end:].rstrip()
    if inner.endswith(")"):
        inner = inner[:-1]
    return inner.strip()


def classify(text: str, start: int = 0, end: int = 0) -> Form:
    f = Form(text=text, start=start, end=end, kind="other")
    m = _SUGAR.match(text)
    if m:
        params = " ".join(m.group(2).split())
        inner = _close(text, m.end())
        f.kind, f.name, f.params = "define-fn", m.group(1), f"({params})"
        f.body = f"(lambda ({params}) {inner})" if inner else ""
        return f
    m = _NAMED.match(text)
    if m:
        init = _close(text, m.end())
        f.name, f.body = m.group(1), init
        if re.match(r"^\(lambda\b", init):
            f.kind = "define-fn"
            pm = re.match(r"^\(\s*lambda\s+(\([^)]*\)|[^\s()]+)", init)
            raw = pm.group(1) if pm else "()"
            f.params = raw if raw.startswith("(") else f"({raw})"
        else:
            f.kind = "define-var"
        return f
    head = re.match(r"^\((require|load|export|define-[\w-]+)\b", text)
    if head:
        f.kind = head.group(1) if head.group(1) in ("require", "load", "export") else "other"
    return f


def top_forms(src: str) -> list[Form]:
    out: list[Form] = []
    i, n = 0, len(src)
    while i < n:
        i = _skip_ws_comment(src, i)
        if i >= n:
            break
        if src[i] != "(":
            i += 1
            continue
        end = _scan_form(src, i)
        out.append(classify(src[i:end], i, end))
        i = end
    return out


def define_map(src: str) -> dict[str, Form]:
    """name -> last top-level define form (functions and vars)."""
    return {f.name: f for f in top_forms(src) if f.kind in ("define-fn", "define-var")}


def _tokens(body: str) -> list[str]:
    return re.findall(r'"(?:\\.|[^"\\])*"|[^\s()]+', strip_comments(body))


def metadata_only(old: str, new: str) -> bool:
    """True when every differing token is a sha, date or version literal."""
    a, b = _tokens(old), _tokens(new)
    if len(a) != len(b):
        return False
    diff = [(x, y) for x, y in zip(a, b) if x != y]
    return bool(diff) and all(_META_TOKEN.match(x) and _META_TOKEN.match(y) for x, y in diff)


@dataclass
class Commit:
    sha: str
    parent: str
    time: int
    subject: str


def list_commits(repo: Path, *, max_commits: int | None = None) -> list[Commit]:
    """First-parent history (oldest first) of commits that touch *.aura files."""
    out = git(repo, "log", "--first-parent", "--reverse", "--format=%H%x00%P%x00%ct%x00%s", "--", "*.aura")
    commits = []
    for line in out.splitlines():
        parts = line.split("\x00")
        if len(parts) < 4:
            continue
        sha, parents, ct, subject = parts[:4]
        plist = parents.split()
        if not plist:
            continue  # root commit: no parent to diff against
        commits.append(Commit(sha=sha, parent=plist[0], time=int(ct), subject=subject))
    if max_commits:
        commits = commits[-max_commits:]
    return commits


def changed_aura(repo: Path, c: Commit, filt: str = "M") -> list[str]:
    out = git(repo, "diff", "--name-only", f"--diff-filter={filt}", c.parent, c.sha, "--", "*.aura")
    return [p for p in out.split("\n") if p.endswith(".aura")]


def unit_id(repo_name: str, rel: str, name: str, parent: str, child: str) -> str:
    key = f"{repo_name}:{rel}:{name}:{parent[:12]}:{child[:12]}"
    return "pv2-" + hashlib.sha1(key.encode()).hexdigest()[:12]


@dataclass
class Unit:
    id: str
    repo: str
    file: str
    name: str
    parent: str
    child: str
    commit_group: str
    commit_time: int
    old_form: str
    new_form: str
    old_body: str
    new_body: str
    status: str = "candidate"
    reason: str = ""
    info: dict = field(default_factory=dict)


def _added_defines(repo: Path, c: Commit, files: list[str]) -> set[str]:
    added: set[str] = set()
    for rel in files:
        old = show(repo, c.parent, rel) or ""
        new = show(repo, c.sha, rel) or ""
        added |= set(define_map(new)) - set(define_map(old))
    return added


def split_commit(
    repo: Path, repo_name: str, c: Commit, counts: dict[str, int], *, child_helpers: bool = True
) -> list[Unit]:
    """One Unit per changed top-level define. Skipped changes are counted, not returned."""
    files = changed_aura(repo, c)
    units: list[Unit] = []
    touched: set[str] = set()
    src_files = [f for f in files if not is_harness(f)]
    counts["files-harness"] = counts.get("files-harness", 0) + (len(files) - len(src_files))
    if not src_files:
        return units
    # Helpers that appear on the child in any added or modified file.
    added = _added_defines(repo, c, changed_aura(repo, c, "AM"))
    for rel in src_files:
        old_src = show(repo, c.parent, rel)
        new_src = show(repo, c.sha, rel)
        if old_src is None or new_src is None:
            continue
        if max(len(old_src), len(new_src)) > MAX_FILE_CHARS:
            counts["skip:file-too-large"] = counts.get("skip:file-too-large", 0) + 1
            continue
        old_defs, new_defs = define_map(old_src), define_map(new_src)
        for name, nf in new_defs.items():
            of = old_defs.get(name)
            if of is None:
                continue
            if of.text == nf.text:
                continue
            touched.add(name)

            def skip(why: str) -> None:
                counts["skip:" + why] = counts.get("skip:" + why, 0) + 1

            if bodies_equivalent(of.text, nf.text):
                skip("comment-or-whitespace")
                continue
            if _META_NAME.search(name) or "traj_id" in nf.text or metadata_only(of.text, nf.text):
                skip("metadata")
                continue
            if nf.kind != "define-fn" or of.kind != "define-fn" or not nf.body or not of.body:
                skip("non-lambda")
                continue
            if not paren_balanced(nf.body):
                skip("unbalanced")
                continue
            refs = code_symbols(nf.body) - {name}
            needs_new = sorted(refs & added)
            if needs_new and not child_helpers:
                skip("child-helper")
                continue
            units.append(
                Unit(
                    id=unit_id(repo_name, rel, name, c.parent, c.sha),
                    repo=repo_name,
                    file=rel,
                    name=name,
                    parent=c.parent,
                    child=c.sha,
                    commit_group=f"{repo_name}@{c.sha[:12]}",
                    commit_time=c.time,
                    old_form=of.text,
                    new_form=nf.text,
                    old_body=of.body,
                    new_body=nf.body,
                    info={"added_refs": needs_new} if needs_new else {},
                )
            )
    # Every define this commit changed: a rebind that only works together with a
    # sibling change (e.g. a callee arity change) is labeled `-coupled`.
    allchanged = sorted(touched)
    for u in units:
        u.info["commit_changed"] = [n for n in allchanged if n != u.name]
    return units
