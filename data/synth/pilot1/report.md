# Synthetic-task pilot 1 (Hybrid-Gym style, P1)

- generator: `scripts/synth.py` (seed 1, 20 defines sampled from 396 candidates)
- pool: pipeline batch2 train+eval contexts (closed on Aura 133d701); all sampled defines are from aura-pad
- teacher: `MiniMax-M3.1-Flash` (id confirmed via /v1/models and a 1-token call)
- gate host: Aura binary sha256 `a309986417906374…` (reused build of 52dd925fd from /workspace/rv/bin-new, not pinned;
  dev image ghcr.io/cybrid-systems/dev:v1.0.9), self-test 3/3 OK

| task | n | schema ok | pass (gate) | notes |
|---|---|---|---|---|
| locate | 20 | 18 | 17 | 2 schema: gold body itself holds a banned token; 1 teacher altered the body |
| deps | 20 | 18 | 17 | same 2 schema; 1 body altered |
| fill | 20 | 16 | 15 | typecheck gate only; 2/15 bodies equal the original; 3 no JSON array, 1 not a rebind |

49 accepted rows in `accepted.jsonl`. Fill rows have no behavioral test yet
(`verify.test.status = none`, so the exporter weights them x0.5).

Teacher usage: 92 calls, 148,223 prompt + 447,184 completion tokens (mostly reasoning),
wall 937 s at 8 workers; per-call p50 latency locate 29.9 s, deps 18.4 s, fill 74.6 s.

After this run the candidate filter drops gold bodies that hold contract-banned tokens
(eval, fences, ...), which removes the 2 shared schema failures.
