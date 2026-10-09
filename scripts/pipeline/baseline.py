"""Stage 8 (optional): zero-shot MiniMax baseline on the held-out eval split.

Each eval row is sent as the SFT chat prompt (system contract + closed context +
intent). The answer must be one legal patch array; it is scored by strict apply
on the row's context and by whether the post-source equals the gold post-source.
"""

from __future__ import annotations

import json
import re
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from apply import apply_patch, apply_succeeded
from edsl_patch import PatchError, normalize_source, validate_patch
from export_sft import to_sft

from .host import Host
from .intent import load_minimax


def _ask(cfg: dict, messages: list[dict]) -> str:
    body = {"model": cfg["model"], "messages": messages, "max_tokens": 8000, "temperature": 0.0}
    req = urllib.request.Request(
        cfg["base"] + "/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Authorization": "Bearer " + cfg["_key"], "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=240) as resp:
        data = json.load(resp)
    text = data["choices"][0]["message"]["content"] or ""
    return re.sub(r"(?s)<think>.*?</think>", "", text).strip()


def _parse(text: str):
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    i, j = t.find("["), t.rfind("]")
    if i < 0 or j < i:
        raise PatchError("no JSON array")
    return json.loads(t[i : j + 1])


def score_row(cfg: dict, row: dict) -> dict:
    msgs = to_sft(row)["messages"][:2]
    out = {"id": row["id"], "legal": False, "apply_ok": False, "gold_match": False, "same_name": False}
    t0 = time.time()
    try:
        text = _ask(cfg, msgs)
    except Exception as e:  # noqa: BLE001
        out["error"] = f"api: {e}"[:200]
        return out
    try:
        patch = validate_patch(_parse(text))
        out["legal"] = True
    except (PatchError, ValueError, json.JSONDecodeError) as e:
        out["error"] = f"illegal: {e}"[:200]
        out["answer_head"] = text[:200]
        return out
    last = patch[-1]
    out["same_name"] = last.get("name") == row["target"][-1]["name"]
    try:
        res = apply_patch(row["input"]["source"], patch, timeout=60)
        out["apply_ok"] = apply_succeeded(res)
        gold = (row.get("verify") or {}).get("expected_source") or ""
        out["gold_match"] = out["apply_ok"] and normalize_source(res.get("source") or "") == normalize_source(gold)
        if not out["apply_ok"]:
            out["reject"] = str((res.get("synthesis") or {}).get("detail"))[:200]
    except PatchError as e:
        out["error"] = f"apply: {e}"[:200]
    out["sec"] = round(time.time() - t0, 1)
    return out


def run_baseline(out_dir: Path, host: Host, minimax_env: str | None = None, split: str = "eval") -> dict:
    cfg = load_minimax(Path(minimax_env) if minimax_env else None)
    if cfg is None:
        raise SystemExit("baseline: MiniMax config/key not found")
    host.activate()
    rows = [json.loads(l) for l in (out_dir / f"{split}.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    with ThreadPoolExecutor(max_workers=4) as ex:
        res = list(ex.map(lambda r: score_row(cfg, r), rows))
    n = max(1, len(res))
    summary = {
        "model": cfg["model"],
        "split": split,
        "n": len(res),
        "legal_rate": round(sum(r["legal"] for r in res) / n, 3),
        "strict_apply_rate": round(sum(r["apply_ok"] for r in res) / n, 3),
        "gold_match_rate": round(sum(r["gold_match"] for r in res) / n, 3),
        "same_name_rate": round(sum(r["same_name"] for r in res) / n, 3),
        "host": host.aura_sha,
        "rows": res,
    }
    (out_dir / f"baseline-{split}.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return summary
