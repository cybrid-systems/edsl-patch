# Held-out vertical eval

These files are **never** passed to `export_sft.py` (commercial or otherwise).
`--doctor` fails if a holdout id appears in catalog plants/rewrites **or** if a
holdout `step` / `tick` / `energy` pretty-source equals a catalog plant field
(whitespace-normalized). Dynamics are hidden: not Euler clones, not quote-only.

```bash
python3 scripts/eval_verticals.py --doctor
python3 scripts/eval_verticals.py
```

Thresholds (gold targets): frozen_escape=0, twin_probe_rate≥0.7, session_id_rate=1.0, refuse_rate≥0.8.

`sft: false` kill-identity rows are wrong fixtures (not commercial positives).
A planted frozen rebind in `--completions` must yield frozen_escape>0 and a
non-zero exit.

Mode B: `--completions path.jsonl` with `{id, target}` model outputs.
