# Rollout + pipeline run — 2026-10-16

Host: Aura `133d701` (clean clone, RelWithDebInfo, pinned flags, image `ghcr.io/cybrid-systems/dev:v1.0.9`), bin sha256 `bc0401d5…`, pipeline self-test OK.
edsl-patch `212a250`. Unit tests: 171 passed, 1 skipped.
Proposers are catalog (and `agent-ask` for twin/session); no model is needed for rollouts. Pipeline intents: MiniMax-M3 (`--intent llm`).

## 1. Replay of the recorded commands (README / schema/rollout.md)

All recorded files reproduce byte-for-byte except:

- `rollout-twin-step` (mass-spring): the `damp-v` fork's post-energy is now 1849, where the clipped −5 term used to be. r goes from −6.8 to −2.04, so `damp-v` replaces `energy-watch` as the SFT hop. `data/raw/rollout-twin-step.jsonl` was refreshed.
- `rollout-siblings`: content is identical. Only `meta.rev` would be blank on this box, because the sibling repos are not at `../<repo>`. The file was not touched.

## 2. Broad rollouts (all plants, `--host aura`)

| run | trajs | hops | synth/refuse | SFT gold | gold rate | traj cut |
|---|---|---|---|---|---|---|
| twin-step d4 f4 | 4 | 30 | 21/9 | 13 | 0.43 | refuse ×4 |
| twin-step d2 agent-ask | 4 | 18 | 18/0 | 9 | 0.50 | depth ×3, aura ×1 |
| session-hot d2 f4 | 4 | 32 | 24/8 | 24 | 0.75 | depth ×4 |
| session-hot d2 agent-ask | 4 | 32 | 24/8 | 24 | 0.75 | depth ×4 |
| arith-core d1 f8 | 4 | 27 | 23/4 | 17 | 0.63 | depth ×4 (7 mismatch) |
| kv-mini d1 f4 | 4 | 14 | 10/4 | 5 | 0.36 | depth ×4 |
| list-fp d1 f4 | 4 | 10 | 6/4 | 4 (all refuse) | 0.40 | depth ×4 |
| controller arith p0/p1/p3/p4 | 4 | 27 | 23/4 | 1/7/2/7 = 17 | 0.63 | — |

Each synthesis fork was re-run in isolation (`mutate:rebind` → `eval-current` → probe), 96 unique forks in total. All returned `#t` with a working probe, so the host rejected **0**.

Failure taxonomy:

- **twin `two-mass` catalog/plant mismatch.** The catalog bodies read `"x"`/`"v"`, but the plant has `x1`/`v1`/`x2`/`v2`. `damp-v`, `pd` and `clip-u` fail the probe, which leaves 2 hops (catalog) or a cut of `aura` (agent-ask).
- **list-fp.** 0 synthesis gold, because the catalog bodies never beat refuse.
- **Driver note.** The arith/kv/fp emitters treat any truthy `mutate:rebind` result as success, so a rejection list would count as success. siblings and the controller use `(eq? rb #t)`. This had no effect in this run because every rebind returned `#t`.

## 3. Pipeline v2 batch2 vs batch1 (same repo HEADs, new host)

| | batch1 (Aura 3b21350) | batch2 (Aura 133d701) |
|---|---|---|
| units | 373 | 373 |
| closure_ok (labelable) | 144 (38.6%) | 252 (67.6%) |
| KEEP | 126 (33.8%) | 235 (63.0%) |
| ROLLBACK | 4 (1.1%) | 17 (4.6%) |
| closure failure (all / host-typecheck) | 0.553 / 0.481 | 0.217 / 0.146 |
| apply_ok given closed | 0.889 | 0.960 |
| KEEP tested share | 0.373 | 0.430 |
| train / eval / neg | 95 / 12 / 4 | 166 / 21 / 17 |
| SFT export | 95 | 166 (all blocking gates PASS; only `train-size>=200` warns) |

Per repo:

- aura-pad: 336 units. closure_ok 133 → 235. KEEP 115 → 218. ROLLBACK 4 → 17: 7 test-regressed (m9/m6/m11) and 10 rejected-arity or unbound.
- aura-redis: 37 units. KEEP 11 → 17.

Remaining host-typecheck rejects (filed upstream):

- Keyword literals are unbound in the post-mutate typecheck: `:switch` 38, `:create` 9, `:list` 5, `:def-use` 4, `:current` 4 (aura-pad, 28 units). Filed as aura#4544.
- `hash-ref` with a default inside a `let`, and `tcp-recv` with `maxlen`, fail on arity (aura-redis, 15 units). Filed as aura#4545.

Test environment:

- 10 test pairs hit the 90 s timeout. aura-pad `m11_test` stalls in `sec-c2` once sections a1…c1 have run; each subset finishes in under 12 s.
- At aura-pad HEAD, `gap_test` fails on `(or *utf-hi* (> c 126))` with `c="back"`. That is an aura-pad bug, exposed by the #4493 if-condition change.
- Several aura-pad files load `utf.aura` through `AURA_PAD_HOME` or a literal `/workspace/aura-pad`, which TreeCache does not rewrite.

## 4. batch2-ext (new targets)

| repo | units | closure_ok | KEEP | ROLLBACK | train/eval |
|---|---|---|---|---|---|
| aura-kernel-sink | 57 | 44 | 42 | 2 | 31/3 |
| aura-aima | 13 | 11 | 11 | 0 | 7/2 |
| aura-rl-sutton | 45 | 42 | 42 | 0 | 21/2 |

Totals: closure failure 0.076, train 59, SFT export 53.
