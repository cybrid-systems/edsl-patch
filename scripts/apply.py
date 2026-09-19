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

from edsl_patch import PatchError, emit_driver, load_patch, load_sample, sources_match, validate_patch


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

    try:
        result = apply_patch(source, patch)
    except PatchError as e:
        print(json.dumps({"ok": False, "error": str(e)}), file=sys.stderr)
        return 1

    if expected:
        result["match"] = sources_match(result.get("source") or "", expected)
        if result.get("ok") and not result["match"]:
            result["ok"] = False
            result["error"] = "post-source mismatch"

    public = {k: v for k, v in result.items() if k != "_raw"}
    print(json.dumps(public, ensure_ascii=False))
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
