"""Stage 5: per-define intent from the diff (never the commit subject).

Two sources:
  template  deterministic sentence built from the old/new body diff
  llm       MiniMax (OpenAI-compatible chat API), validated and sanitized;
            falls back to the template when the answer breaks a rule

Banned in any intent: auto score / telemetry lines, model names,
personal phrases, CJK text, absolute paths, commit SHAs.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.request
from pathlib import Path

from parse_aura import code_symbols, lambda_params, strip_comments

# Telemetry / self-evolve score lines ("146/148 (score-improved)", "smoke 148/148 load 2660").
AUTO_LINE = re.compile(
    r"\b\d+\s*/\s*\d+\b|score-improved|\bscore\s*[:=]?\s*[\d(]|\bsmoke\s+\d|ops/s|\bgen(eration)?\s*[→>]|→\s*\d|"
    r"\bload\s+\d+|\bp(50|90|95|99)\b|\b(KEEP|DROP)\b|\bfitness\s*[:=]?\s*\d|\bwin rate\b|"
    r"\d+(\.\d+)?\s*(ms|µs|us|%)(?![\w-])"
)
MODEL_NAMES = re.compile(
    r"minimax(-m\d)?|deepseek[\w.-]*|gpt-?\d[\w.-]*|claude[\w.-]*|\bgrok[\w.-]*|qwen[\w.-]*|gemini[\w.-]*|"
    r"llama[\w.-]*|kimi[\w.-]*|\bo[134]-?(mini)?\b",
    re.I,
)
PERSONAL = re.compile(r"\b(user|i|we|my|our|me)\b\s*(said|asked|wants|prefer|:)|\(user[:)]|多发散", re.I)
CJK = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]")
ABS_PATH = re.compile(r"/(workspace|home|Users|tmp|root)/")
SHA = re.compile(r"\b[0-9a-f]{7,40}\b")
MAX_INTENT = 280


def violations(text: str) -> list[str]:
    out = []
    if not text or not text.strip():
        out.append("empty")
    if len(text) > MAX_INTENT:
        out.append("too-long")
    if AUTO_LINE.search(text):
        out.append("auto-line")
    if MODEL_NAMES.search(text):
        out.append("model-name")
    if PERSONAL.search(text):
        out.append("personal")
    if CJK.search(text):
        out.append("cjk")
    if ABS_PATH.search(text):
        out.append("abs-path")
    if SHA.search(text) and re.search(r"[a-f]", SHA.search(text).group(0)):
        out.append("sha")
    return out


_CORE = {
    "lambda", "let", "let*", "letrec", "begin", "define", "set!", "quote", "else", "if", "cond", "case",
    "when", "unless", "and", "or", "not", "do", "while", "try", "catch", "list", "cons", "car", "cdr",
    "+", "-", "*", "/", "=", "<", ">", "<=", ">=", "eq?", "equal?", "null?", "pair?",
}


def _local_names(body: str) -> set[str]:
    """Lambda params, let/let*/letrec bindings and named-let names."""
    from parse_aura import _scan_form

    txt = strip_comments(body)
    names: set[str] = set()
    for params in re.findall(r"\(lambda\s*\(([^)]*)\)", txt):
        names |= set(params.split())
    for m in re.finditer(r"\((?:let\*?|letrec\*?)\s+(?:([^\s()]+)\s+)?\(", txt):
        if m.group(1):
            names.add(m.group(1))
        start = m.end() - 1
        end = _scan_form(txt, start)
        inner = txt[start + 1 : end - 1]
        i = 0
        while i < len(inner):
            if inner[i] == "(":
                j = _scan_form(inner, i)
                b = re.match(r"\(\s*([^\s()]+)", inner[i:j])
                if b:
                    names.add(b.group(1))
                i = j
            else:
                i += 1
    return names


def _calls(body: str) -> set[str]:
    raw = set(re.findall(r"\(\s*([^\s()\"';#]+)", strip_comments(body)))
    return {c for c in raw if not re.match(r"^[-+]?[\d.]+$", c) and len(c) > 1} - _CORE - _local_names(body)


def _rank(calls: set[str]) -> list[str]:
    # Project helpers (namespaced) first, then the rest.
    return sorted(calls, key=lambda c: (":" not in c, c))


def _literals(body: str) -> set[str]:
    txt = strip_comments(body)
    return set(re.findall(r'"(?:\\.|[^"\\])*"', txt)) | set(re.findall(r"(?<![\w-])-?\d+(?:\.\d+)?(?![\w-])", txt))


_SPECIAL = {"lambda", "let", "let*", "letrec", "begin", "define", "set!", "quote", "else"}


def template_intent(name: str, old_body: str, new_body: str) -> str:
    """Deterministic, diff-derived intent."""
    po, pn = lambda_params(old_body), lambda_params(new_body)
    co, cn = _calls(old_body), _calls(new_body)
    lo, ln = _literals(old_body), _literals(new_body)
    bits: list[str] = []
    if po != pn:
        added = sorted(pn - po)
        dropped = sorted(po - pn)
        if added:
            bits.append("take " + ", ".join(added[:3]) + (" as a new parameter" if len(added) == 1 else " as new parameters"))
        if dropped:
            bits.append("drop the " + ", ".join(dropped[:3]) + " parameter" + ("s" if len(dropped) > 1 else ""))
    new_calls = _rank(cn - co)
    gone_calls = _rank(co - cn)
    if new_calls:
        bits.append("call " + ", ".join(new_calls[:4]))
    if gone_calls:
        bits.append("stop calling " + ", ".join(gone_calls[:4]))
    for kw, label in (("if", "branch"), ("cond", "case"), ("while", "loop")):
        d = new_body.count(f"({kw} ") - old_body.count(f"({kw} ")
        if d > 0:
            bits.append(f"add {d} {label}" + ("es" if label == "branch" and d > 1 else ("s" if d > 1 else "")))
        elif d < 0:
            bits.append(f"remove {-d} {label}" + ("es" if label == "branch" and -d > 1 else ("s" if -d > 1 else "")))
    lit_new = sorted(ln - lo, key=len)[:2]
    if lit_new and len(bits) < 3:
        bits.append("use " + " and ".join(l if len(l) <= 24 else l[:21] + '..."' for l in lit_new))
    size = len(strip_comments(new_body)) - len(strip_comments(old_body))
    if not bits:
        bits.append("restructure the body" + (" (longer)" if size > 40 else " (shorter)" if size < -40 else ""))
    text = f"Change {name} to " + "; ".join(bits) + "."
    if len(text) > MAX_INTENT:
        text = text[: MAX_INTENT - 1].rsplit(" ", 1)[0] + "."
    return text


def load_minimax(env_file: Path | None = None) -> dict | None:
    env_file = env_file or Path(os.path.expanduser("~/.config/aura-build/minimax.env"))
    if not env_file.is_file():
        return None
    cfg: dict[str, str] = {}
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            cfg[k.strip()] = v.strip().strip('"').strip("'")
    keyf = cfg.get("MINIMAX_API_KEY_FILE", "")
    kp = Path(os.path.expanduser(keyf)) if keyf else None
    if kp is None or not kp.is_file():
        # The env file may be mounted elsewhere (e.g. a container HOME).
        kp = env_file.parent / (Path(keyf).name if keyf else "minimax_api_key")
    if not kp.is_file() or not cfg.get("MINIMAX_BASE_URL"):
        return None
    return {
        "base": cfg["MINIMAX_BASE_URL"].rstrip("/"),
        "model": cfg.get("MINIMAX_MODEL", "MiniMax-M3"),
        "_key": kp.read_text(encoding="utf-8").strip(),
    }


PROMPT = """You label one code change for a training set.
Language: Aura (a Scheme dialect). Define: {name} (file {file}).

OLD:
{old}

NEW:
{new}

Write ONE imperative sentence (max 30 words) that tells a programmer what to change in {name} and why, as a task request.
Describe the behavior change, not the syntax. Name helpers or parameters only if needed.
Do not mention scores, benchmarks, tests, commits, model names, people, or numbers of lines.
Answer with the sentence only."""


def _clip(s: str, n: int = 2500) -> str:
    return s if len(s) <= n else s[:n] + "\n…"


def llm_intent(cfg: dict, name: str, file: str, old_body: str, new_body: str, retries: int = 2) -> str | None:
    body = {
        "model": cfg["model"],
        "messages": [
            {
                "role": "user",
                "content": PROMPT.format(name=name, file=Path(file).name, old=_clip(old_body), new=_clip(new_body)),
            }
        ],
        "max_tokens": 6000,
        "temperature": 0.2,
    }
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(
                cfg["base"] + "/chat/completions",
                data=json.dumps(body).encode(),
                headers={"Authorization": "Bearer " + cfg["_key"], "Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=180) as resp:
                data = json.load(resp)
            choice = data["choices"][0]
            if choice.get("finish_reason") == "length":
                continue
            text = choice["message"]["content"] or ""
            if "<think>" in text and "</think>" not in text:
                continue
            text = re.sub(r"(?s)<think>.*?</think>", "", text).strip()
            text = " ".join(text.split()).strip("\"'` ")
            if text:
                return text
        except Exception:  # noqa: BLE001 - network / API errors fall back to the template
            time.sleep(2 * (attempt + 1))
    return None


def sanitize(text: str) -> str:
    text = MODEL_NAMES.sub("the model", text)
    text = CJK.sub("", text)
    text = ABS_PATH.sub("/", text)
    return " ".join(text.split())


def make_intent(name: str, file: str, old_body: str, new_body: str, cfg: dict | None) -> tuple[str, str, list[str]]:
    """(intent, intent_source, rejected-llm-violations)"""
    rejected: list[str] = []
    if cfg is not None:
        got = llm_intent(cfg, name, file, old_body, new_body)
        if got:
            got = sanitize(got)
            bad = violations(got)
            if not bad:
                return got, "llm", []
            rejected = bad
        else:
            rejected = ["llm-error"]
    tpl = sanitize(template_intent(name, old_body, new_body))
    return tpl, "template", rejected
