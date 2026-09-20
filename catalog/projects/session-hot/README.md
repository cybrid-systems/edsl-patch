# session-hot

Hot function is `tick`: `(book, sess) → (hash "q" number "sess" sess')`.
Runtime identity is the **sess value**, not the frozen `*session*` binding.

## Plants

| id | Difference |
|----|------------|
| `tick-hold` | identity-preserving default, q=0 |
| `tick-seq` | tick increments `seq` by 1 |
| `tick-book-bidask` | book keys bid/ask (not mid) |
| `tick-gated` | q goes through frozen `gate` |

## Keep (farm)

`scripts/farm.py` `session_should_keep` after K=8 `(tick book sess)` hops:

- apply ok; rewrite.keep is not false
- `id`, `fd`, `alive` identical to the pre-patch snapshot
- `seq` increased by 0, 1, or K (never jump)
- `q` is a number every tick

`kill-alive` / `swap-fd` / `jump-seq` drop from the positive farm.

## Negatives (`rewrites.neg.jsonl`, keep=false)

- `kill-alive` — alive=#f
- `swap-fd` — fd changed
- `jump-seq` — seq += 5

These are **not** SFT positives. Farm must drop them; refuse miner may use them.

## Forbidden

rebind `*session*` or `gate`; eval; c-load; fiber; synthesize.

## Quota

800 keep. cap-per-summary 120.
