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

id, fd, alive identical; seq +0 or +1 only. q is a number every tick.

## Negatives (`rewrites.neg.jsonl`, keep=false)

- `kill-alive` — alive=#f
- `swap-fd` — fd changed
- `jump-seq` — seq += 5

These are **not** SFT positives. Farm must drop them; refuse miner may use them.

## Forbidden

rebind `*session*` or `gate`; eval; c-load; fiber; synthesize.

## Quota

800 keep. cap-per-summary 120.
