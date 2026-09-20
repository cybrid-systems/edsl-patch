# session-hot

Long-session vertical: rebind `quote` without dropping session identity.
First wave uses an in-process hash standing in for a TCP/FIX session.

## High-quality rewrite

`quote` maps a book hash → number (price offset or signed size). After rebind,
session `id` / `fd` / `alive` stay identical. `*session*` is frozen.

## Eval assumption

In-process hash session; **no socket**. Book is `bid`/`ask` or `mid`/`spread`.
Farm later calls `(quote book)` K=8 times.

## Forbidden

- rebind `*session*` or (this wave) `gate`
- close / `alive` `#f` in body
- `eval`, `c-load`, `fiber:`, `synthesize:`, ffi tokens

## Keep condition (farm later)

Session id, fd, alive identical after apply + N quote calls. Quote returns a number.

## Quota

800 keep. cap-per-summary 120. Default session budget smoke; `full` is opt-in.

## How Grok Build may extend

Add plants/rewrites in this directory only. `names`/`hot` stay `[\"quote\"]` this wave.
Re-run `python3 scripts/catalog.py --check --projects --project session-hot`.
Do not commit `data/raw/`. Do not use real TCP/FIX.
