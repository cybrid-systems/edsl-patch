# Held-out vertical eval

These files are **never** passed to `export_sft.py`. They are not catalog plant ids.

```bash
python3 scripts/eval_verticals.py --doctor
python3 scripts/eval_verticals.py
```

Thresholds (gold targets): frozen_escape=0, twin_probe_rate≥0.7, session_id_rate=1.0, refuse_rate≥0.8.

Mode B: `--completions path.jsonl` with `{id, target}` model outputs.
