"""CLI: python3 -m scripts.pipeline {collect,selftest,export,pin} ..."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import ROOT
from .host import HostMismatch, file_sha256, load_pin, require_host, resolve_host, selftest, PIN_PATH


def _host_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--aura-bin", help="Aura binary (default: $AURA_BIN, then pins/aura-host.json bin_hints)")
    p.add_argument("--aura-lib", help="Aura stdlib (default: <aura-src>/lib)")
    p.add_argument("--aura-src", help="Aura checkout of the pinned SHA (default: two levels above the binary)")


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(prog="python3 -m scripts.pipeline", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("collect", help="run every stage on one or more repos")
    c.add_argument("--repo", action="append", required=True, type=Path)
    c.add_argument("--out", required=True, type=Path)
    _host_args(c)
    c.add_argument("--intent", choices=("template", "llm"), default="template")
    c.add_argument("--minimax-env", help="MiniMax env file (default ~/.config/aura-build/minimax.env)")
    c.add_argument("--no-tests", action="store_true")
    c.add_argument("--no-child-helpers", action="store_true", help="skip units whose body needs a define added by the same commit")
    c.add_argument("--max-commits", type=int, default=None, help="newest N commits per repo")
    c.add_argument("--max-units", type=int, default=None)
    c.add_argument("--workers", type=int, default=4)
    c.add_argument("--eval-share", type=float, default=0.15)
    c.add_argument("--budget", type=int, default=None, help="context char budget (default MAX_FOCUS_CHARS)")
    c.add_argument("--keep-trees", action="store_true")
    c.add_argument("--export", action="store_true", help="export sft.jsonl when all blocking gates pass")

    s = sub.add_parser("selftest", help="check the pinned host and its strict keep gate")
    _host_args(s)

    e = sub.add_parser("export", help="export train.jsonl through scripts/export_sft.py if gates pass")
    e.add_argument("--out", required=True, type=Path)
    e.add_argument("--force", action="store_true")

    b = sub.add_parser("baseline", help="zero-shot MiniMax baseline on the eval split (strict apply + gold match)")
    b.add_argument("--out", required=True, type=Path)
    b.add_argument("--split", default="eval")
    b.add_argument("--minimax-env")
    _host_args(b)

    pn = sub.add_parser("pin", help="print (or --write) a pin entry for a binary")
    _host_args(pn)
    pn.add_argument("--write", action="store_true")

    a = ap.parse_args(argv)
    host_kw = {}
    if a.cmd in ("collect", "selftest", "pin", "baseline"):
        host_kw = {"aura_bin": a.aura_bin, "aura_lib": a.aura_lib, "aura_src": a.aura_src}

    if a.cmd == "pin":
        pin = load_pin()
        from .host import find_bin, _git_head

        b = find_bin(pin, a.aura_bin)
        digest = file_sha256(b)
        src = Path(a.aura_src) if a.aura_src else b.parent.parent
        info = {"bin": str(b), "bin_sha256": digest, "src_sha": _git_head(src), "pinned_sha": pin["aura_sha"]}
        print(json.dumps(info, indent=2))
        if a.write:
            if info["src_sha"] != pin["aura_sha"]:
                print("pin: refusing to add a binary built from a different Aura SHA", file=sys.stderr)
                return 3
            if digest not in pin["bin_sha256"]:
                pin["bin_sha256"].append(digest)
                PIN_PATH.write_text(json.dumps(pin, indent=2) + "\n", encoding="utf-8")
        return 0

    if a.cmd == "selftest":
        try:
            host = resolve_host(**host_kw)
        except HostMismatch as ex:
            print(f"selftest: {ex}", file=sys.stderr)
            return 3
        st = selftest(host)
        print(json.dumps(host.as_manifest(), indent=2))
        return 0 if st["ok"] else 3

    if a.cmd == "baseline":
        from .baseline import run_baseline

        try:
            host = require_host(**host_kw)
        except HostMismatch as ex:
            print(f"baseline: refusing to run: {ex}", file=sys.stderr)
            return 3
        sm = run_baseline(a.out.resolve(), host, a.minimax_env, a.split)
        print(json.dumps({k: v for k, v in sm.items() if k != "rows"}, indent=2))
        return 0

    if a.cmd == "export":
        from .run import export

        return export(a.out, a.force)

    from parse_aura import MAX_FOCUS_CHARS
    from .run import collect, export

    try:
        host = require_host(**host_kw)
    except HostMismatch as ex:
        print(f"collect: refusing to run: {ex}", file=sys.stderr)
        return 3
    opts = {
        "intent": a.intent,
        "minimax_env": a.minimax_env,
        "tests": not a.no_tests,
        "child_helpers": not a.no_child_helpers,
        "max_commits": a.max_commits,
        "max_units": a.max_units,
        "workers": a.workers,
        "eval_share": a.eval_share,
        "budget": a.budget or MAX_FOCUS_CHARS,
        "keep_trees": a.keep_trees,
    }
    repos = [r.resolve() for r in a.repo]
    R = collect(repos, a.out.resolve(), host, opts, argv)
    if a.export:
        return export(a.out.resolve())
    return 0 if R["train"]["n"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
