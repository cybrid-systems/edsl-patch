"""Pinned Aura host: sha256 check, source SHA check, behavioral self-test."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from . import ROOT

PIN_PATH = ROOT / "pins" / "aura-host.json"


class HostMismatch(RuntimeError):
    pass


@dataclass
class Host:
    bin: Path
    lib: Path
    aura_sha: str
    bin_sha256: str
    src_sha: str = ""
    selftest: dict = field(default_factory=dict)

    def env(self) -> dict[str, str]:
        return {
            "AURA_BIN": str(self.bin),
            "AURA_LIB": str(self.lib),
            # Only the stdlib: never a sibling worktree.
            "AURA_PATH": str(self.lib),
            "AURA_SANDBOX": "off",
            "AURA_PIPELINE_STRICT": "0",
        }

    def activate(self) -> None:
        os.environ.update(self.env())

    def as_manifest(self) -> dict:
        return {
            "aura_sha": self.aura_sha,
            "src_sha": self.src_sha,
            "bin": str(self.bin),
            "bin_sha256": self.bin_sha256,
            "lib": str(self.lib),
            "selftest": self.selftest,
        }


def load_pin(path: Path = PIN_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _git_head(path: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(path), "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (subprocess.CalledProcessError, OSError):
        return ""


def find_bin(pin: dict, explicit: str | None = None) -> Path:
    if explicit:
        return Path(explicit).resolve()
    env = os.environ.get("AURA_BIN")
    if env:
        return Path(env).resolve()
    for hint in pin.get("bin_hints") or []:
        p = (ROOT / hint).resolve()
        if p.is_file():
            return p
    raise HostMismatch("no Aura binary: pass --aura-bin or set AURA_BIN")


def resolve_host(
    *,
    aura_bin: str | None = None,
    aura_lib: str | None = None,
    aura_src: str | None = None,
    pin: dict | None = None,
) -> Host:
    """Refuse unless the binary sha256 is pinned and the source SHA (when known) matches."""
    pin = pin or load_pin()
    bin_path = find_bin(pin, aura_bin)
    if not bin_path.is_file():
        raise HostMismatch(f"Aura binary not found: {bin_path}")
    digest = file_sha256(bin_path)
    allowed = set(pin.get("bin_sha256") or [])
    if digest not in allowed:
        raise HostMismatch(
            f"host mismatch: sha256({bin_path})={digest} is not pinned in pins/aura-host.json "
            f"(aura {pin.get('aura_sha', '')[:12]})"
        )
    src = Path(aura_src).resolve() if aura_src else bin_path.parent.parent
    src_sha = _git_head(src)
    if src_sha and src_sha != pin["aura_sha"]:
        raise HostMismatch(f"host mismatch: {src} is at {src_sha[:12]}, pin is {pin['aura_sha'][:12]}")
    lib = Path(aura_lib).resolve() if aura_lib else src / "lib"
    if not (lib / "std").is_dir():
        raise HostMismatch(f"Aura stdlib not found at {lib}")
    return Host(bin=bin_path, lib=lib, aura_sha=pin["aura_sha"], bin_sha256=digest, src_sha=src_sha)


# A rebind that calls an unbound function must be rejected; a plain one must be #t.
SELFTEST_CASES = (
    ("accepts-plain-rebind", "(define f (lambda (x) x))", "f", "(lambda (x) (+ x 1))", True),
    ("rejects-unbound-call", "(define f (lambda (x) x))", "f", "(lambda (x) (not-a-real-fn x))", False),
    (
        "rejects-arity-mismatch",
        "(define g (lambda (a b) (+ a b)))\n(define f (lambda (x) (g x x)))",
        "f",
        "(lambda (x) (g x))",
        False,
    ),
)


def selftest(host: Host) -> dict:
    """Behavioral check of the strict keep gate on this host."""
    from apply import apply_patch, apply_succeeded
    from parse_aura import patch_for

    host.activate()
    results = {}
    ok = True
    for name, src, fn, body, want in SELFTEST_CASES:
        try:
            got = apply_succeeded(apply_patch(src, patch_for(fn, body, name), timeout=60))
        except Exception as e:  # noqa: BLE001
            got = f"error: {e}"[:200]
        results[name] = {"want": want, "got": got}
        if got is not want:
            ok = False
    host.selftest = {"ok": ok, "cases": results}
    return host.selftest


def require_host(**kw) -> Host:
    host = resolve_host(**kw)
    st = selftest(host)
    if not st["ok"]:
        raise HostMismatch(f"host self-test failed: {json.dumps(st['cases'])}")
    return host
