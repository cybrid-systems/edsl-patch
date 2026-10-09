"""Stage 3 check + stage 4: load the context, strict apply, tests, KEEP/ROLLBACK.

Strict apply means `mutate:rebind` returned exactly #t (apply.apply_succeeded).
Every unit is applied twice on the same context:

  identity  rebind to the parent body. If the host rejects this, the context
            is not closed; the unit is a closure failure, not a label.
  child     rebind to the child body. Rejected -> ROLLBACK.

Where the repo has a cheap Aura test that loads the changed file, it runs on
the parent tree and on the parent tree with the child define spliced in.
A test that passed on the parent and fails after the splice -> ROLLBACK.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tarfile
import io
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from apply import apply_patch, apply_succeeded, run_aura_program
from edsl_patch import PatchError, normalize_source
from parse_aura import patch_for

from .units import Form, show, top_forms

LOAD_MARK = "PIPELINE_CTX_LOADED"
_LOAD_ERR = re.compile(r"(?im)unbound variable|^\s*error\b|\berror:|exception:|arity mismatch")
_TEST_FILE = re.compile(r"(^|/)(test_[^/]*|[^/]*_test|[^/]*_smoke)\.aura$")
_TEST_SKIP = re.compile(r'std/socket|std/ffi|std/tcp|getenv "AURA_REDIS_PORT"|c-load|ffi:')
_TEST_FAIL = re.compile(r"\bFAIL(?:ED|URE)?\b|WANT=")
_TEST_ERR = re.compile(r"(?m)^\s*(error|panic|exception)\b.*$", re.I)
_TEST_OKMARK = re.compile(r"(?m)^[A-Z0-9_]+_OK$|ALL PASSED")
_TEST_CHECK = re.compile(r"(?m)^\s*(T .* OK|OK .*|  OK .*)$")
TEST_TIMEOUT = 90
MAX_TESTS = 2


def reject_category(detail: object) -> str:
    text = str(detail)
    if "unbound variable" in text:
        return "unbound"
    if "arity mismatch" in text:
        return "arity"
    if "type" in text and "error" in text:
        return "type"
    if "parse" in text or "read" in text:
        return "parse"
    if text in ("False", "None", "#f", ""):
        return "error"
    return "other"


def load_check(context: str, timeout: int = 60) -> tuple[bool, str]:
    prog = context.rstrip() + f'\n(display "{LOAD_MARK}")\n(newline)\n'
    try:
        out = run_aura_program(prog, timeout=timeout)
    except PatchError as e:
        return False, str(e)[-400:]
    if LOAD_MARK not in out:
        return False, out[-400:]
    bad = _LOAD_ERR.search(out)
    if bad:
        return False, out[max(0, bad.start() - 120) : bad.end() + 200]
    return True, ""


@dataclass
class ApplyResult:
    ident_ok: bool = False
    ok: bool = False
    detail: str = ""
    category: str = ""
    source: str = ""
    ident_source: str = ""
    prints_same: bool = False
    error: str = ""
    sec: float = 0.0


def strict_apply(context: str, name: str, old_body: str, new_body: str, summary: str, timeout: int = 60) -> ApplyResult:
    r = ApplyResult()
    t0 = time.time()
    try:
        ident = apply_patch(context, patch_for(name, old_body, "identity"), timeout=timeout)
        r.ident_ok = apply_succeeded(ident)
        r.ident_source = ident.get("source") or ""
        if not r.ident_ok:
            r.detail = str((ident.get("synthesis") or {}).get("detail"))[:600]
            r.category = reject_category(r.detail)
            r.sec = time.time() - t0
            return r
    except PatchError as e:
        r.error = "identity: " + str(e)[:400]
        r.category = "illegal-token" if "illegal token" in str(e) or "extra define" in str(e) else "error"
        r.sec = time.time() - t0
        return r
    try:
        res = apply_patch(context, patch_for(name, new_body, summary), timeout=timeout)
    except PatchError as e:
        r.error = "child: " + str(e)[:400]
        r.category = "illegal-token" if "illegal token" in str(e) or "extra define" in str(e) else "error"
        r.sec = time.time() - t0
        return r
    r.ok = apply_succeeded(res)
    r.source = res.get("source") or ""
    if not r.ok:
        r.detail = str((res.get("synthesis") or {}).get("detail"))[:600]
        r.category = reject_category(r.detail)
    else:
        r.prints_same = normalize_source(r.source) == normalize_source(r.ident_source)
    r.sec = time.time() - t0
    return r


# ---------------------------------------------------------------- tests


@dataclass
class TestRun:
    test: str
    status: str  # ran | timeout
    sec: float
    ok_marker: bool = False
    checks: int = 0
    fails: frozenset = frozenset()
    errors: frozenset = frozenset()
    tail: str = ""

    @property
    def signal(self) -> bool:
        return self.status == "ran" and (self.ok_marker or self.checks > 0)

    def short(self) -> str:
        if self.status != "ran":
            return self.status
        return f"ok_marker={int(self.ok_marker)} checks={self.checks} fails={len(self.fails)} errors={len(self.errors)}"


def summarize_output(test: str, out: str, sec: float) -> TestRun:
    fails = frozenset(l.strip() for l in out.splitlines() if _TEST_FAIL.search(l))
    # Positions shift when the spliced define changes length; compare messages only.
    errors = frozenset(re.sub(r"\b\d+:\d+:\s*", "", m.group(0)).strip() for m in _TEST_ERR.finditer(out))
    return TestRun(
        test,
        "ran",
        sec,
        ok_marker=bool(_TEST_OKMARK.search(out)),
        checks=len(_TEST_CHECK.findall(out)),
        fails=fails,
        errors=errors,
        tail=out[-300:],
    )


def regressed(base: TestRun, after: TestRun) -> bool:
    """Compare against the parent run, so failures that already exist do not count."""
    if not base.signal:
        return False
    if after.status != "ran":
        return True
    if base.ok_marker and not after.ok_marker:
        return True
    if after.fails - base.fails or after.errors - base.errors:
        return True
    return after.checks < base.checks


class TreeCache:
    """Parent trees materialized with `git archive`, abs repo paths rewritten."""

    def __init__(self, root: Path, host_env: dict[str, str]):
        self.root = root
        self.env = host_env
        self._locks: dict[str, threading.Lock] = {}
        self._lock = threading.Lock()
        self._baseline: dict[tuple[str, str, str], TestRun] = {}

    def lock(self, key: str) -> threading.Lock:
        with self._lock:
            return self._locks.setdefault(key, threading.Lock())

    def tree(self, repo: Path, repo_name: str, sha: str) -> Path:
        dest = self.root / f"{repo_name}-{sha[:12]}"
        if (dest / ".pipeline-ready").is_file():
            return dest
        if dest.exists():
            shutil.rmtree(dest)
        dest.mkdir(parents=True)
        data = subprocess.check_output(["git", "-C", str(repo), "archive", "--format=tar", sha])
        with tarfile.open(fileobj=io.BytesIO(data)) as tf:
            tf.extractall(dest, filter="data")
        pat = re.compile(r"/workspace/" + re.escape(repo_name) + r"/")
        for p in dest.rglob("*.aura"):
            txt = p.read_text(encoding="utf-8", errors="replace")
            if pat.search(txt):
                p.write_text(pat.sub(str(dest) + "/", txt), encoding="utf-8")
        (dest / ".pipeline-ready").write_text("ok\n")
        return dest

    def run_test(self, tree: Path, test_rel: str) -> TestRun:
        env = os.environ.copy()
        env.update(self.env)
        env["AURA_PATH"] = f"{self.env['AURA_LIB']}:{tree}"
        t0 = time.time()
        try:
            proc = subprocess.run(
                [self.env["AURA_BIN"], test_rel],
                cwd=tree,
                env=env,
                capture_output=True,
                text=True,
                timeout=TEST_TIMEOUT,
                start_new_session=True,
            )
        except subprocess.TimeoutExpired:
            return TestRun(test_rel, "timeout", time.time() - t0)
        out = (proc.stdout or "") + "\n" + (proc.stderr or "")
        return summarize_output(test_rel, out, time.time() - t0)

    def baseline(self, repo_name: str, sha: str, tree: Path, test_rel: str) -> TestRun:
        key = (repo_name, sha, test_rel)
        if key not in self._baseline:
            self._baseline[key] = self.run_test(tree, test_rel)
        return self._baseline[key]


def discover_tests(repo: Path, sha: str, target_rel: str, ls: tuple[str, ...]) -> list[str]:
    """Cheap Aura tests at `sha` that load/require the changed file."""
    stem = target_rel[:-5] if target_rel.endswith(".aura") else target_rel
    hits: list[tuple[int, str]] = []
    for rel in ls:
        if not _TEST_FILE.search(rel):
            continue
        src = show(repo, sha, rel)
        if not src or _TEST_SKIP.search(src):
            continue
        refs = False
        for f in top_forms(src):
            if f.kind in ("load", "require"):
                m = re.match(r'^\((?:load|require)\s+"([^"]+)"', f.text)
                arg = m.group(1) if m else ""
                a = arg[:-5] if arg.endswith(".aura") else arg
                if a == stem or a.endswith("/" + stem):
                    refs = True
                    break
        if refs:
            hits.append((len(src), rel))
    return [rel for _, rel in sorted(hits)[:MAX_TESTS]]


def splice(parent_src: str, old_form: str, new_form: str, helpers: list[str]) -> str | None:
    """Replace the parent define with the child define (plus new helpers before it)."""
    i = parent_src.rfind(old_form)
    if i < 0:
        return None
    pre = "".join(h + "\n\n" for h in helpers)
    return parent_src[:i] + pre + new_form + parent_src[i + len(old_form) :]


@dataclass
class TestLabel:
    status: str  # none | pass | regressed | parent-fail | splice-failed
    runs: list[dict] = field(default_factory=list)
    sec: float = 0.0


def run_unit_tests(
    cache: TreeCache,
    repo: Path,
    repo_name: str,
    unit,
    tests: list[str],
    helper_texts: list[str],
) -> TestLabel:
    if not tests:
        return TestLabel("none")
    t0 = time.time()
    with cache.lock(f"{repo_name}-{unit.parent}"):
        tree = cache.tree(repo, repo_name, unit.parent)
        target = tree / unit.file
        orig = target.read_text(encoding="utf-8")
        pat = re.compile(r"/workspace/" + re.escape(repo_name) + r"/")
        old_form = pat.sub(str(tree) + "/", unit.old_form)
        new_form = pat.sub(str(tree) + "/", unit.new_form)
        patched = splice(orig, old_form, new_form, [pat.sub(str(tree) + "/", h) for h in helper_texts])
        if patched is None:
            return TestLabel("splice-failed", sec=time.time() - t0)
        runs = []
        any_signal = False
        regressed_any = False
        try:
            for t in tests:
                base = cache.baseline(repo_name, unit.parent, tree, t)
                target.write_text(patched, encoding="utf-8")
                try:
                    after = cache.run_test(tree, t)
                finally:
                    target.write_text(orig, encoding="utf-8")
                cmd = f"cd <tree:{unit.parent[:12]}> && AURA_PATH=$AURA_LIB:. $AURA_BIN {t}"
                reg = regressed(base, after)
                runs.append(
                    {
                        "test": t,
                        "cmd": cmd,
                        "parent": base.short(),
                        "patched": after.short(),
                        "regressed": reg,
                        "parent_sec": round(base.sec, 2),
                        "patched_sec": round(after.sec, 2),
                        "new_fails": sorted(after.fails - base.fails)[:5] + sorted(after.errors - base.errors)[:5],
                    }
                )
                if base.signal:
                    any_signal = True
                    if reg:
                        regressed_any = True
        finally:
            target.write_text(orig, encoding="utf-8")
    status = "regressed" if regressed_any else ("pass" if any_signal else "no-signal")
    return TestLabel(status, runs, time.time() - t0)
