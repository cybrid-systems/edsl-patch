#!/usr/bin/env python3
"""Load and legally-check the closed L0/L1 rewrite catalog. No Aura, no LLM."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from edsl_patch import PatchError, validate_patch
from parse_aura import extract_defines, patch_for

PLANTS = ROOT / "catalog" / "plants.jsonl"
REWRITES = ROOT / "catalog" / "rewrites.jsonl"

BANNED = ("define", "eval", "synthesize:define", "fiber:spawn")
PROJECTS_ROOT = ROOT / "catalog" / "projects"
ORCH_BAN = ("agent:", "fiber:", "synthesize:")


def read_jsonl(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def load_plants(path: Path = PLANTS) -> list[dict]:
    return read_jsonl(path)


def load_rewrites(path: Path = REWRITES) -> list[dict]:
    return read_jsonl(path)


def retarget(rewrite: dict, name: str) -> dict:
    out = dict(rewrite)
    out["name"] = name
    return out


def rewrite_patch(rewrite: dict) -> list[dict]:
    return patch_for(rewrite["name"], rewrite["body"], rewrite["summary"])


def dummy_source(name: str) -> str:
    return f"(define {name} (lambda (x) 0))"


def is_noop(plant: dict, rewrite: dict, name: str) -> bool:
    defs = extract_defines(plant["source"])
    body = rewrite["body"]
    return defs.get(name) == body


def lambda_arity(body: str) -> int:
    import re

    m = re.search(r"\(lambda\s*\(([^)]*)\)", body or "")
    if not m:
        return -1
    params = [p for p in m.group(1).split() if p]
    return len(params)


def list_projects(root: Path = PROJECTS_ROOT) -> list[str]:
    ids = []
    if not root.is_dir():
        return ids
    for p in sorted(root.iterdir()):
        if p.is_dir() and (p / "plants.jsonl").is_file() and (p / "rewrites.jsonl").is_file():
            ids.append(p.name)
    return ids


def load_project(pid: str, root: Path = PROJECTS_ROOT) -> tuple[list[dict], list[dict]]:
    d = root / pid
    return load_plants(d / "plants.jsonl"), load_rewrites(d / "rewrites.jsonl")


def project_pairs(plants: list[dict], rewrites: list[dict]) -> list[tuple[dict, dict, str]]:
    out = []
    for p in plants:
        defs = extract_defines(p["source"])
        for name in p.get("names") or []:
            plant_ar = lambda_arity(defs.get(name) or "")
            for rw in rewrites:
                r = retarget(rw, name)
                rw_ar = int(rw.get("arity") or lambda_arity(rw.get("body") or ""))
                if plant_ar >= 0 and rw_ar >= 0 and plant_ar != rw_ar:
                    continue
                if is_noop(p, r, name):
                    continue
                out.append((p, r, name))
    return out


def check_project(pid: str, plants: list[dict], rewrites: list[dict]) -> list[str]:
    errs: list[str] = []
    if len(plants) < 4:
        errs.append(f"{pid}: need ≥4 plants, got {len(plants)}")
    if len(rewrites) < 8:
        errs.append(f"{pid}: need ≥8 rewrites, got {len(rewrites)}")
    summaries = []
    ids = []
    for rw in rewrites:
        rid = rw.get("id")
        if not isinstance(rid, str) or not rid:
            errs.append(f"{pid}: rewrite missing id")
            continue
        if rid in ids:
            errs.append(f"{pid}: duplicate rewrite id {rid}")
        ids.append(rid)
        body = rw.get("body") or ""
        if "(define" in body:
            errs.append(f"{pid}:{rid}: body contains define")
        for tok in ("eval", "synthesize:define", "fiber:spawn"):
            if tok in body:
                errs.append(f"{pid}:{rid}: body contains {tok}")
        try:
            validate_patch(rewrite_patch(retarget(rw, rw.get("name") or "f")))
        except PatchError as e:
            errs.append(f"{pid}:{rid}: {e}")
        summaries.append(rw.get("summary"))
        if pid == "orch-pure":
            blob = body
            for tok in ORCH_BAN:
                if tok in blob:
                    errs.append(f"{pid}:{rid}: orch-pure forbids {tok}")
    if len(set(s for s in summaries if s)) < 8:
        errs.append(f"{pid}: need ≥8 distinct summaries")
    for p in plants:
        src = p.get("source") or ""
        if pid == "orch-pure":
            for tok in ORCH_BAN:
                if tok in src:
                    errs.append(f"{pid}:{p.get('id')}: plant forbids {tok}")
        names = p.get("names") or []
        hot = p.get("hot")
        frozen = p.get("frozen")
        if hot is not None:
            if names != hot:
                errs.append(f"{pid}:{p.get('id')} names must equal hot")
            if frozen and set(hot) & set(frozen):
                errs.append(f"{pid}:{p.get('id')} hot ∩ frozen nonempty")
            for rw in rewrites:
                rname = rw.get("name")
                if rname and rname not in hot:
                    errs.append(f"{pid}:{rw.get('id')} rewrite name {rname} not in hot")
            defs = extract_defines(src)
            for sym in list(hot) + list(frozen or []):
                if sym not in defs and f"(define {sym}" not in src and f"(define ({sym}" not in src:
                    errs.append(f"{pid}:{p.get('id')} missing define {sym}")
        if not names:
            errs.append(f"{pid}:{p.get('id')} missing names")
        if not src.strip():
            errs.append(f"{pid}:{p.get('id')} empty source")
    return errs


def check(plants: list[dict], rewrites: list[dict]) -> list[str]:
    errs: list[str] = []
    if len(plants) < 6:
        errs.append(f"need ≥6 plants, got {len(plants)}")
    if len(rewrites) < 8:
        errs.append(f"need ≥8 rewrites, got {len(rewrites)}")
    summaries = []
    ids = []
    for rw in rewrites:
        rid = rw.get("id")
        if not isinstance(rid, str) or not rid:
            errs.append("rewrite missing stable id")
            continue
        if rid in ids:
            errs.append(f"duplicate rewrite id {rid}")
        ids.append(rid)
        body = rw.get("body") or ""
        for tok in BANNED:
            if tok == "define" and "(define" in body:
                errs.append(f"{rid}: body contains define")
            elif tok != "define" and tok in body:
                errs.append(f"{rid}: body contains {tok}")
        try:
            validate_patch(rewrite_patch(rw))
        except PatchError as e:
            errs.append(f"{rid}: {e}")
        dummy = dummy_source(rw["name"])
        try:
            validate_patch(rewrite_patch(rw))
        except PatchError as e:
            errs.append(f"{rid} dummy: {e}")
        summaries.append(rw.get("summary"))
        if extract_defines(dummy).get(rw["name"]) == rw["body"]:
            pass  # dummy is 0; rewrite may equal 0 for summary zero
    if len(set(summaries)) < 8:
        errs.append(f"need ≥8 distinct summaries, got {sorted(set(summaries))}")
    for p in plants:
        names = p.get("names") or []
        if not names:
            errs.append(f"plant {p.get('id')} missing names")
        src = p.get("source") or ""
        if not src.strip():
            errs.append(f"plant {p.get('id')} empty source")
    return errs


def pairs(plants: list[dict], rewrites: list[dict]) -> list[tuple[dict, dict, str]]:
    out = []
    for p in plants:
        for name in p.get("names") or []:
            for rw in rewrites:
                r = retarget(rw, name)
                if is_noop(p, r, name):
                    continue
                out.append((p, r, name))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="legal-only; no Aura")
    ap.add_argument("--projects", action="store_true", help="check catalog/projects/<id>/")
    ap.add_argument("--project", type=str, default="", help="single project id")
    ap.add_argument("--plants", type=Path, default=PLANTS)
    ap.add_argument("--rewrites", type=Path, default=REWRITES)
    args = ap.parse_args(argv)
    if args.check and (args.projects or args.project):
        ids = [args.project] if args.project else list_projects()
        if not ids:
            print("catalog: no projects", file=sys.stderr)
            return 1
        errs: list[str] = []
        for pid in ids:
            plants, rewrites = load_project(pid)
            errs.extend(check_project(pid, plants, rewrites))
            n = len(project_pairs(plants, rewrites))
            print(f"catalog: {pid} plants={len(plants)} rewrites={len(rewrites)} pairs={n}")
        if errs:
            for e in errs:
                print(f"catalog: {e}", file=sys.stderr)
            return 1
        print(f"catalog: ok projects={len(ids)}")
        return 0
    plants = load_plants(args.plants)
    rewrites = load_rewrites(args.rewrites)
    if args.check:
        errs = check(plants, rewrites)
        if errs:
            for e in errs:
                print(f"catalog: {e}", file=sys.stderr)
            return 1
        n = len(pairs(plants, rewrites))
        print(f"catalog: ok plants={len(plants)} rewrites={len(rewrites)} pairs={n}")
        return 0
    print(f"catalog: plants={len(plants)} rewrites={len(rewrites)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
