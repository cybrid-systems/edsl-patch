# synth batch1 (MiniMax-M3.1-Flash, 300 defines, 8 own Aura repos)

Host: pins/aura-host-synth.json (bin sha256 a3099864…, aura source sha unknown), image dev:v1.0.9.
Pool: --per-repo-cap 45 at each repo HEAD (heads in summary.json), 312 closed candidates, 300 sampled (seed 2).
Wall 3738 s, 1278 calls, 1.02M prompt / 4.94M completion tokens.

| task | pass/n | notes |
|---|---|---|
| locate | 236/300 | schema 46, body-changed 12 |
| deps | 229/300 | schema 38, deps-mismatch 17, body-changed 13 |
| fill | 123/300 (17 exact) | behavior-diff 49, host-reject 44, schema 42, parse 34 |

Fill behavior gate (172 host-ok fills): pass 93, diff 49 (rejected), no-signal 30 (kept, test_status no-signal).
Accepted 588: tiers locate easy78/med122/hard36; deps easy74/med121/hard34; fill trivial11/easy42/med63/hard7.
Known: 3 defines with describe-failed carry no repo tag in by_repo ("None").
