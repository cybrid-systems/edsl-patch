# Pipeline v2 quality report — `batch2`

- edsl-patch: `212a250e9a95`; pipeline 2.0.0, code sha256 `e26228513ebf2b8a…`
- host: Aura `133d701688ae`, bin sha256 `bc0401d5068dbc70…`, self-test OK
- repo `aura-pad` @ `3cf0f86e7d58` (https://github.com/cybrid-systems/aura-pad.git)
- repo `aura-redis` @ `e8840d7cbdb5` (https://github.com/cybrid-systems/aura-redis.git)
- intents: llm (MiniMax-M3 @ https://api.minimaxi.com/v1)

## Funnel per repo

| repo | commits_scanned | commits_with_units | units | closure_ok | identity_ok | apply_ok | prints_same | host_reject | KEEP | ROLLBACK | after_dedup | train | eval | train_neg | eval_neg |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| aura-pad | 160 | 81 | 336 | 235 | 235 | 225 | 0 | 0 | 218 | 17 | 171 | 152 | 19 | 16 | 1 |
| aura-redis | 37 | 8 | 37 | 17 | 17 | 17 | 0 | 0 | 17 | 0 | 16 | 14 | 2 | 0 | 0 |

## Drop / skip reasons

- dedup:cap-commit: 43
- aura-pad:files-harness: 39
- aura-pad:closure-fail:identity-host-unbound: 28
- aura-pad:skip:illegal-token: 27
- aura-pad:closure-fail:context-too-long: 22
- aura-redis:skip:non-lambda: 21
- aura-pad:skip:non-lambda: 19
- aura-pad:skip:abs-path-in-context: 15
- aura-redis:closure-fail:identity-host-arity: 15
- aura-pad:skip:schema: 8
- dedup:cap-name: 5
- aura-redis:closure-fail:identity-host-unbound: 3
- aura-pad:skip:comment-or-whitespace: 1
- aura-pad:closure-fail:identity-host-arity: 1
- aura-redis:closure-fail:context-too-long: 1
- aura-redis:skip:illegal-token: 1
- aura-redis:files-harness: 0

## Rates

- closure_failure: 0.217
- closure_failure_context: 0.0
- closure_failure_host_typecheck: 0.146
- closure_failure_budget: 0.071
- apply_ok_given_closed: 0.96
- keep_share_of_labeled: 0.933
- keep_tested_share: 0.43
- units_to_train: 0.445
- intent_llm_share: 0.992

- closure failure kinds: {'host': 47, 'budget': 23}
- host typecheck: unbound symbols that the repo does not define (top): {':switch': 22, ':create': 9, ':list': 5, ':def-use': 4, ':current': 4, 'hot-strategy:heal!': 3, 'hot-strategy:swap!': 3, 'mutate:boundary-safe?': 2, 'mutate:safety-snapshot': 2, 'pd:helper': 1, 'pd:hshadow': 1, 'command-line': 1, 'hot-strateg': 1, 'choose-f': 1}

## Labels

- all: {'KEEP': 235, 'ROLLBACK': 17}
- ROLLBACK reasons: {'rejected-arity-coupled': 5, 'test-regressed': 7, 'rejected-unbound-coupled': 1, 'rejected-arity': 4}
- KEEP test status: {'none': 132, 'pass': 101, 'no-signal': 2}

## train (n=166)

- exact_dup_rows: 0
- near_dup_rows: 0
- conflict_rows: 0
- intent_shared_rows: 0
- intent_auto_line_rows: 0
- intent_violation_rows: 0
- intent_mentions_name_rows: 114
- intent_source: {'llm': 166}
- secret_rows: 0
- abs_path_rows: 0
- schema_invalid_rows: 0
- expected_eq_input_rows: 0
- commit_groups: 56
- max_rows_per_commit: 8
- multi_unit_commit_rows: 148
- per_repo: {'aura-redis': 14, 'aura-pad': 152}
- test: {'none': 77, 'pass': 87, 'no-signal': 2}
- prompt_chars: {'n': 166, 'min': 239, 'p50': 2323, 'p90': 6213, 'max': 10239, 'mean': 3010.6}
- prompt_tokens_est: {'n': 166, 'min': 79, 'p50': 774, 'p90': 2071, 'max': 3413, 'mean': 1003.2}
- target_tokens_est: {'n': 166, 'min': 87, 'p50': 236, 'p90': 801, 'max': 4322, 'mean': 424.3}

## eval (n=21)

- exact_dup_rows: 0
- near_dup_rows: 0
- conflict_rows: 0
- intent_shared_rows: 0
- intent_auto_line_rows: 0
- intent_violation_rows: 0
- intent_mentions_name_rows: 15
- intent_source: {'llm': 20, 'template': 1}
- secret_rows: 0
- abs_path_rows: 0
- schema_invalid_rows: 0
- expected_eq_input_rows: 0
- commit_groups: 10
- max_rows_per_commit: 7
- multi_unit_commit_rows: 16
- per_repo: {'aura-redis': 2, 'aura-pad': 19}
- test: {'none': 18, 'pass': 3}
- prompt_chars: {'n': 21, 'min': 719, 'p50': 1879, 'p90': 5459, 'max': 6875, 'mean': 2361.2}
- prompt_tokens_est: {'n': 21, 'min': 239, 'p50': 626, 'p90': 1819, 'max': 2291, 'mean': 786.6}
- target_tokens_est: {'n': 21, 'min': 100, 'p50': 218, 'p90': 364, 'max': 568, 'mean': 249.1}

## all (n=252)

- exact_dup_rows: 0
- near_dup_rows: 0
- conflict_rows: 0
- intent_shared_rows: 0
- intent_auto_line_rows: 0
- intent_violation_rows: 0
- intent_mentions_name_rows: 177
- intent_source: {'llm': 250, 'template': 2}
- secret_rows: 0
- abs_path_rows: 0
- schema_invalid_rows: 0
- expected_eq_input_rows: 0
- commit_groups: 68
- max_rows_per_commit: 31
- multi_unit_commit_rows: 229
- per_repo: {'aura-redis': 17, 'aura-pad': 235}
- test: {'none': 142, 'pass': 101, 'regressed': 7, 'no-signal': 2}
- prompt_chars: {'n': 252, 'min': 239, 'p50': 2527, 'p90': 6213, 'max': 10239, 'mean': 3078.5}
- prompt_tokens_est: {'n': 252, 'min': 79, 'p50': 842, 'p90': 2071, 'max': 3413, 'mean': 1025.8}
- target_tokens_est: {'n': 252, 'min': 87, 'p50': 236, 'p90': 813, 'max': 4322, 'mean': 408.5}

## Export gates

| gate | level | ok | value |
|---|---|---|---|
| train-nonempty | block | PASS | 166 |
| train-size>=200 | warn | FAIL | 166 |
| host-pinned+selftest | block | PASS | bc0401d5068d |
| schema-valid | block | PASS | 0 |
| train-all-keep-strict | block | PASS | {'KEEP': 166} |
| secrets==0 | block | PASS | 0 |
| abs-paths==0 | block | PASS | 0 |
| exact-dup==0 | block | PASS | 0 |
| conflicts==0 | block | PASS | 0 |
| near-dup<=2% | block | PASS | 0 |
| expected==input==0 | block | PASS | 0 |
| intent-auto-lines==0 | block | PASS | 0 |
| intent-model/personal==0 | block | PASS | 0 |
| intent-shared<=5% | block | PASS | 0 |
| source<=MAX_FOCUS_CHARS | block | PASS | 0 |
| no-commit-group-crosses-split | block | PASS | 0 |
| eval-nonempty | warn | PASS | 21 |
| closure-failure(context)<=10% | block | PASS | 0.0 |
| closure-failure(all)<=30% | warn | PASS | 0.217 |
| tested-share>=30% | warn | PASS | 0.43 |
| max-rows-per-commit<=8 | block | PASS | 8 |

**Export allowed: yes**

