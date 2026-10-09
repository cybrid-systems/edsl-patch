# Pipeline v2 quality report — `batch1`

- edsl-patch: `1ffffa2038f9`; pipeline 2.0.0, code sha256 `afcfc22a8b602ad6…`
- host: Aura `3b213503eb45`, bin sha256 `1296bd4efbe6ecd7…`, self-test OK
- repo `aura-pad` @ `3cf0f86e7d58` (https://github.com/cybrid-systems/aura-pad.git)
- repo `aura-redis` @ `e8840d7cbdb5` (https://github.com/cybrid-systems/aura-redis.git)
- intents: llm (MiniMax-M3 @ https://api.minimax.cn/v1)

## Funnel per repo

| repo | commits_scanned | commits_with_units | units | closure_ok | identity_ok | apply_ok | prints_same | host_reject | KEEP | ROLLBACK | after_dedup | train | eval | train_neg | eval_neg |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| aura-pad | 160 | 81 | 336 | 133 | 133 | 117 | 0 | 14 | 115 | 4 | 96 | 86 | 10 | 4 | 0 |
| aura-redis | 37 | 8 | 37 | 11 | 11 | 11 | 0 | 0 | 11 | 0 | 11 | 9 | 2 | 0 | 0 |

## Drop / skip reasons

- aura-pad:closure-fail:identity-host-unbound: 85
- aura-pad:closure-fail:identity-host-arity: 46
- aura-pad:files-harness: 39
- aura-pad:skip:illegal-token: 27
- aura-pad:closure-fail:context-too-long: 22
- aura-redis:skip:non-lambda: 21
- aura-redis:closure-fail:identity-host-unbound: 21
- aura-pad:skip:non-lambda: 19
- dedup:cap-commit: 16
- aura-pad:skip:abs-path-in-context: 15
- aura-pad:skip:schema: 8
- aura-pad:host-reject:child-host-arity: 7
- aura-pad:host-reject:child-host-unbound: 7
- aura-redis:closure-fail:identity-host-arity: 2
- dedup:cap-name: 2
- aura-pad:skip:comment-or-whitespace: 1
- aura-redis:closure-fail:context-too-long: 1
- aura-redis:closure-fail:identity-host-type: 1
- aura-redis:skip:illegal-token: 1
- dedup:cap-shape: 1
- aura-redis:files-harness: 0

## Rates

- closure_failure: 0.553
- closure_failure_context: 0.0
- closure_failure_host_typecheck: 0.481
- closure_failure_budget: 0.071
- apply_ok_given_closed: 0.889
- keep_share_of_labeled: 0.969
- keep_tested_share: 0.373
- units_to_train: 0.255
- intent_llm_share: 0.977

- closure failure kinds: {'host': 155, 'budget': 23}
- host typecheck: unbound symbols that the repo does not define (top): {'try': 62, 'catch': 57, 'apply': 22, 'while': 18, 'workspace': 15, 'current-time-ms': 11, ':switch': 9, 'ast:restore': 7, 'engine:metrics': 6, 'query:defines': 5, 'query:code': 5, ':current': 4, 'mutate:set-agent-fingerprint': 3, ':create': 3, 'define-lookup': 3}

## Labels

- all: {'KEEP': 126, 'ROLLBACK': 4}
- ROLLBACK reasons: {'test-regressed': 2, 'rejected-arity-coupled': 1, 'rejected-arity': 1}
- KEEP test status: {'none': 75, 'pass': 47, 'no-signal': 4}

## train (n=95)

- exact_dup_rows: 0
- near_dup_rows: 0
- conflict_rows: 0
- intent_shared_rows: 0
- intent_auto_line_rows: 0
- intent_violation_rows: 0
- intent_mentions_name_rows: 79
- intent_source: {'llm': 92, 'template': 3}
- secret_rows: 0
- abs_path_rows: 0
- schema_invalid_rows: 0
- expected_eq_input_rows: 0
- commit_groups: 38
- max_rows_per_commit: 8
- multi_unit_commit_rows: 79
- per_repo: {'aura-redis': 9, 'aura-pad': 86}
- test: {'none': 48, 'pass': 43, 'no-signal': 4}
- prompt_chars: {'n': 95, 'min': 177, 'p50': 1866, 'p90': 5188, 'max': 10020, 'mean': 2291.1}
- prompt_tokens_est: {'n': 95, 'min': 59, 'p50': 622, 'p90': 1729, 'max': 3340, 'mean': 763.4}
- target_tokens_est: {'n': 95, 'min': 87, 'p50': 196, 'p90': 492, 'max': 2286, 'mean': 293.6}

## eval (n=12)

- exact_dup_rows: 0
- near_dup_rows: 0
- conflict_rows: 0
- intent_shared_rows: 0
- intent_auto_line_rows: 0
- intent_violation_rows: 0
- intent_mentions_name_rows: 6
- intent_source: {'llm': 12}
- secret_rows: 0
- abs_path_rows: 0
- schema_invalid_rows: 0
- expected_eq_input_rows: 0
- commit_groups: 8
- max_rows_per_commit: 4
- multi_unit_commit_rows: 6
- per_repo: {'aura-redis': 2, 'aura-pad': 10}
- test: {'none': 11, 'pass': 1}
- prompt_chars: {'n': 12, 'min': 723, 'p50': 1862, 'p90': 2210, 'max': 5916, 'mean': 1985.7}
- prompt_tokens_est: {'n': 12, 'min': 241, 'p50': 620, 'p90': 736, 'max': 1972, 'mean': 661.5}
- target_tokens_est: {'n': 12, 'min': 115, 'p50': 266, 'p90': 359, 'max': 568, 'mean': 268.2}

## all (n=130)

- exact_dup_rows: 0
- near_dup_rows: 0
- conflict_rows: 0
- intent_shared_rows: 0
- intent_auto_line_rows: 0
- intent_violation_rows: 0
- intent_mentions_name_rows: 103
- intent_source: {'llm': 127, 'template': 3}
- secret_rows: 0
- abs_path_rows: 0
- schema_invalid_rows: 0
- expected_eq_input_rows: 0
- commit_groups: 47
- max_rows_per_commit: 20
- multi_unit_commit_rows: 107
- per_repo: {'aura-redis': 11, 'aura-pad': 119}
- test: {'none': 77, 'pass': 47, 'regressed': 2, 'no-signal': 4}
- prompt_chars: {'n': 130, 'min': 177, 'p50': 2013, 'p90': 4931, 'max': 10020, 'mean': 2338.4}
- prompt_tokens_est: {'n': 130, 'min': 59, 'p50': 671, 'p90': 1643, 'max': 3340, 'mean': 779.2}
- target_tokens_est: {'n': 130, 'min': 87, 'p50': 201, 'p90': 492, 'max': 2286, 'mean': 293.1}

## Export gates

| gate | level | ok | value |
|---|---|---|---|
| train-nonempty | block | PASS | 95 |
| train-size>=200 | warn | FAIL | 95 |
| host-pinned+selftest | block | PASS | 1296bd4efbe6 |
| schema-valid | block | PASS | 0 |
| train-all-keep-strict | block | PASS | {'KEEP': 95} |
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
| eval-nonempty | warn | PASS | 12 |
| closure-failure(context)<=10% | block | PASS | 0.0 |
| closure-failure(all)<=30% | warn | FAIL | 0.553 |
| tested-share>=30% | warn | PASS | 0.373 |
| max-rows-per-commit<=8 | block | PASS | 8 |

**Export allowed: yes**

