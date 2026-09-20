#!/usr/bin/env python3
"""Apply a query→synthesis patch on a local Aura host. No LLM."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from edsl_patch import (
    PatchError,
    emit_driver,
    load_patch,
    load_sample,
    sources_match,
    validate_patch,
)


def pick_bin() -> Path:
    env = os.environ.get("AURA_BIN")
    if env and Path(env).is_file() and os.access(env, os.X_OK):
        return Path(env)
    for c in (ROOT.parent / "aura-grok" / "build" / "aura", ROOT.parent / "aura" / "build" / "aura"):
        if c.is_file() and os.access(c, os.X_OK):
            return c
    raise SystemExit("error: aura binary not found. Set AURA_BIN or build ../aura-grok")


def pick_lib() -> Path:
    env = os.environ.get("AURA_LIB")
    if env and (Path(env) / "std").is_dir():
        return Path(env)
    for c in (ROOT.parent / "aura-grok" / "lib", ROOT.parent / "aura" / "lib"):
        if (c / "std").is_dir():
            return c
    raise SystemExit("error: Aura stdlib not found. Set AURA_LIB")


def parse_result(stdout: str) -> dict:
    marker = "EDSL_PATCH_RESULT "
    for line in stdout.splitlines():
        if line.startswith(marker):
            return json.loads(line[len(marker) :])
    raise PatchError("apply driver printed no EDSL_PATCH_RESULT line")


def apply_patch(
    source: str,
    patch: list[dict],
    *,
    timeout: int = 30,
    extra_path: str | Path | None = None,
) -> dict:
    validate_patch(patch)
    bin_path = pick_bin()
    lib = pick_lib()
    env = os.environ.copy()
    paths = [str(lib)]
    if extra_path:
        paths.insert(0, str(extra_path))
    existing = [p for p in env.get("AURA_PATH", "").split(":") if p]
    for p in existing:
        if p not in paths:
            paths.append(p)
    env["AURA_PATH"] = ":".join(paths)
    env["AURA_SANDBOX"] = env.get("AURA_SANDBOX") or "off"
    env["AURA_PIPELINE_STRICT"] = env.get("AURA_PIPELINE_STRICT") or "0"
    with tempfile.TemporaryDirectory(prefix="edsl-patch-") as tmp:
        tmp_path = Path(tmp)
        src_file = tmp_path / "source.aura"
        drv_file = tmp_path / "driver.aura"
        src_file.write_text(source.strip() + "\n", encoding="utf-8")
        drv_file.write_text(emit_driver(src_file, patch), encoding="utf-8")
        proc = subprocess.Popen(
            [str(bin_path), str(drv_file)],
            cwd=tmp_path,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired as e:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                proc.kill()
            proc.wait()
            raise PatchError(f"aura timeout after {timeout}s") from e
        out = (stdout or "") + (("\n" + stderr) if stderr else "")
        if proc.returncode != 0:
            raise PatchError(f"aura exit {proc.returncode}: {out[-2000:]}")
        result = parse_result(out)
        queries = result.get("query")
        if isinstance(queries, list):
            result["query"] = list(reversed(queries))
        result["_raw"] = out
        return result


def run_aura_program(src: str, *, timeout: int = 30) -> str:
    bin_path = pick_bin()
    lib = pick_lib()
    env = os.environ.copy()
    env["AURA_PATH"] = env.get("AURA_PATH") or str(lib)
    env["AURA_SANDBOX"] = env.get("AURA_SANDBOX") or "off"
    env["AURA_PIPELINE_STRICT"] = env.get("AURA_PIPELINE_STRICT") or "0"
    with tempfile.TemporaryDirectory(prefix="edsl-probe-") as tmp:
        f = Path(tmp) / "probe.aura"
        f.write_text(src, encoding="utf-8")
        proc = subprocess.Popen(
            [str(bin_path), str(f)],
            cwd=tmp,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired as e:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                proc.kill()
            proc.wait()
            raise PatchError("aura probe timeout") from e
        out = (stdout or "") + (("\n" + stderr) if stderr else "")
        if proc.returncode != 0:
            raise PatchError(f"aura probe exit {proc.returncode}: {out[-1500:]}")
        return out


def twin_probes(post_source: str, n: int = 40, world: dict | None = None) -> dict:
    world = world or {"x": 2, "v": 1, "t": 0}
    prog = "\n".join(
        [
            post_source,
            f'(define *w* (hash "x" {world["x"]} "v" {world["v"]} "t" {world["t"]}))',
            "(define *n* 0)",
            "(define (go k)",
            "  (if (<= k 0) *w*",
            "    (begin (set! *w* (step *w* (control *w*))) (set! *n* (+ *n* 1)) (go (- k 1)))))",
            f"(go {int(n)})",
            '(display "PROBE ")',
            '(display (json-encode (hash "t" (hash-ref *w* "t") "energy" (energy *w*) "n" *n*)))',
            "(newline)",
        ]
    )
    out = run_aura_program(prog)
    for line in out.splitlines():
        if line.startswith("PROBE "):
            return json.loads(line[len("PROBE ") :])
    raise PatchError("no PROBE line")


def session_probes(post_source: str, k: int = 8) -> dict:
    prog = "\n".join(
        [
            post_source,
            '(define *book* (hash "bid" 1 "ask" 3 "mid" 2 "spread" 2))',
            "(define *qs* '())",
            f"(define *k* {int(k)})",
            "(define *qf* quote)",
            "(define (go i)",
            "  (if (<= i 0) #t",
            "    (begin (set! *qs* (cons (*qf* *book*) *qs*)) (go (- i 1)))))",
            "(go *k*)",
            '(display "PROBE ")',
            '(display (json-encode (hash "id" (hash-ref *session* "id")',
            ' "fd" (hash-ref *session* "fd")',
            ' "alive" (hash-ref *session* "alive"))))',
            "(newline)",
        ]
    )
    out = run_aura_program(prog)
    for line in out.splitlines():
        if line.startswith("PROBE "):
            return json.loads(line[len("PROBE ") :])
    raise PatchError("no PROBE line")


def apply_sample(sample: dict, *, timeout: int = 30) -> dict:
    source = sample["input"]["source"]
    patch = sample.get("target") or []
    verify = sample.get("verify") or {}
    sft = sample.get("sft", True)
    if sft is False:
        try:
            validate_patch(patch, observe=(sample.get("input") or {}).get("observe"))
            result = apply_patch(source, patch, timeout=timeout)
            result["ok"] = False
            result["error"] = "sft-false sample must not validate+apply"
            return result
        except PatchError as e:
            return {"ok": False, "error": str(e), "sft": False}
    result = apply_patch(source, patch, timeout=timeout)
    probes = verify.get("probes") or {}
    if patch and patch[-1].get("kind") == "refuse":
        result["probes"] = {"refuse_noop": True}
        if verify.get("apply_ok") and result.get("ok"):
            result["probe_pass"] = True
        return result
    if probes.get("t_mono") or "energy_after_steps_lt" in probes:
        n = 40
        pre_e = (sample.get("input") or {}).get("observe", {}).get("energy")
        got = twin_probes(result.get("source") or source, n=n)
        result["probes"] = got
        t_ok = got.get("t") == n or got.get("n") == n
        e_ok = True
        lim = probes.get("energy_after_steps_lt")
        if lim is not None:
            e_ok = float(got.get("energy") or 0) < float(lim)
        elif pre_e is not None:
            e_ok = float(got.get("energy") or 0) < float(pre_e)
        result["probe_pass"] = bool(t_ok and e_ok)
        if not result["probe_pass"]:
            result["ok"] = False
            result["error"] = f"twin probe fail t={got} t_ok={t_ok} e_ok={e_ok}"
    if probes.get("session_stable"):
        got = session_probes(result.get("source") or source)
        want = ((sample.get("input") or {}).get("observe") or {}).get("session") or {}
        result["probes"] = got
        ok = (
            int(got.get("id") or -1) == int(want.get("id") or -2)
            and int(got.get("fd") or -1) == int(want.get("fd") or -2)
            and bool(got.get("alive")) is True
        )
        result["probe_pass"] = bool(ok)
        if not ok:
            result["ok"] = False
            result["error"] = f"session identity fail {got}"
    return result


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", help="Aura source_0 string")
    p.add_argument("--source-file", type=Path, help="Aura source_0 file")
    p.add_argument("--patch", type=Path, help="JSON patch array (or sample with target)")
    p.add_argument("--sample", type=Path, help="jsonl/json sample with input+target")
    p.add_argument("--expected", help="expected post-source (optional verify)")
    args = p.parse_args(argv)

    source = None
    patch = None
    expected = args.expected
    if args.sample:
        sample = load_sample(args.sample)
        source = sample["input"]["source"]
        patch = sample["target"]
        expected = expected or (sample.get("verify") or {}).get("expected_source")
    if args.source:
        source = args.source
    if args.source_file:
        source = args.source_file.read_text(encoding="utf-8")
    if args.patch:
        patch = load_patch(args.patch)
    if not source or patch is None:
        p.error("need --sample, or --source/--source-file plus --patch")

    sample_obj = None
    if args.sample:
        sample_obj = load_sample(args.sample)

    try:
        if sample_obj is not None:
            result = apply_sample(sample_obj)
        else:
            result = apply_patch(source, patch)
    except PatchError as e:
        print(json.dumps({"ok": False, "error": str(e)}), file=sys.stderr)
        return 1

    if expected and sample_obj is None:
        result["match"] = sources_match(result.get("source") or "", expected)
        if result.get("ok") and not result["match"]:
            result["ok"] = False
            result["error"] = "post-source mismatch"

    public = {k: v for k, v in result.items() if k != "_raw"}
    print(json.dumps(public, ensure_ascii=False))
    if sample_obj is not None and sample_obj.get("sft") is False:
        return 0 if not result.get("ok") else 2
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
