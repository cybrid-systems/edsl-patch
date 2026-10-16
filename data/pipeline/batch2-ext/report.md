# Pipeline v2 quality report — `batch2-ext`

- edsl-patch: `212a250e9a95`; pipeline 2.0.0, code sha256 `e26228513ebf2b8a…`
- host: Aura `133d701688ae`, bin sha256 `bc0401d5068dbc70…`, self-test OK
- repo `aura-kernel-sink` @ `172527b676f9` (https://github.com/cybrid-systems/aura-kernel-sink.git)
- repo `aura-aima` @ `511726901da3` (https://github.com/cybrid-systems/aura-aima.git)
- repo `aura-rl-sutton` @ `115d803cd73c` (https://github.com/cybrid-systems/aura-rl-sutton.git)
- intents: llm (MiniMax-M3 @ https://api.minimaxi.com/v1)

## Funnel per repo

| repo | commits_scanned | commits_with_units | units | closure_ok | identity_ok | apply_ok | prints_same | host_reject | KEEP | ROLLBACK | after_dedup | train | eval | train_neg | eval_neg |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| aura-kernel-sink | 15 | 13 | 57 | 44 | 44 | 42 | 0 | 0 | 42 | 2 | 34 | 31 | 3 | 2 | 0 |
| aura-aima | 6 | 3 | 13 | 11 | 11 | 11 | 0 | 0 | 11 | 0 | 9 | 7 | 2 | 0 | 0 |
| aura-rl-sutton | 10 | 6 | 45 | 42 | 42 | 42 | 0 | 0 | 42 | 0 | 23 | 21 | 2 | 0 | 0 |

## Drop / skip reasons

- dedup:cap-commit: 19
- aura-kernel-sink:files-harness: 14
- dedup:cap-shape: 10
- aura-kernel-sink:skip:non-lambda: 8
- aura-kernel-sink:skip:schema: 5
- aura-kernel-sink:skip:illegal-token: 4
- aura-rl-sutton:closure-fail:context-load: 3
- aura-aima:files-harness: 2
- aura-kernel-sink:closure-fail:identity-host-unbound: 2
- aura-rl-sutton:files-harness: 1
- aura-rl-sutton:skip:non-lambda: 1
- aura-kernel-sink:closure-fail:identity-host-arity: 1
- aura-kernel-sink:closure-fail:identity-host-type: 1
- aura-aima:closure-fail:context-load: 1
- aura-aima:skip:schema: 1

## Rates

- closure_failure: 0.076
- closure_failure_context: 0.038
- closure_failure_host_typecheck: 0.038
- closure_failure_budget: 0.0
- apply_ok_given_closed: 0.979
- keep_share_of_labeled: 0.979
- keep_tested_share: 0.0
- units_to_train: 0.513
- intent_llm_share: 1.0

- closure failure kinds: {'host': 4, 'context': 4}
- host typecheck: unbound symbols that the repo does not define (top): {'sink-calls': 1, 'label-of': 1, 'hot-sum-sq': 1, 'cold-add': 1}

## Labels

- all: {'KEEP': 95, 'ROLLBACK': 2}
- ROLLBACK reasons: {'rejected-arity': 1, 'rejected-arity-coupled': 1}
- KEEP test status: {'none': 95}

## train (n=59)

- exact_dup_rows: 0
- near_dup_rows: 0
- conflict_rows: 0
- intent_shared_rows: 0
- intent_auto_line_rows: 0
- intent_violation_rows: 0
- intent_mentions_name_rows: 34
- intent_source: {'llm': 59}
- secret_rows: 0
- abs_path_rows: 0
- schema_invalid_rows: 0
- expected_eq_input_rows: 0
- commit_groups: 18
- max_rows_per_commit: 8
- multi_unit_commit_rows: 53
- per_repo: {'aura-rl-sutton': 21, 'aura-kernel-sink': 31, 'aura-aima': 7}
- test: {'none': 59}
- prompt_chars: {'n': 59, 'min': 264, 'p50': 1492, 'p90': 4480, 'max': 7720, 'mean': 2022.7}
- prompt_tokens_est: {'n': 59, 'min': 88, 'p50': 497, 'p90': 1493, 'max': 2573, 'mean': 673.9}
- target_tokens_est: {'n': 59, 'min': 81, 'p50': 174, 'p90': 532, 'max': 1108, 'mean': 269.9}

## eval (n=7)

- exact_dup_rows: 0
- near_dup_rows: 0
- conflict_rows: 0
- intent_shared_rows: 0
- intent_auto_line_rows: 0
- intent_violation_rows: 0
- intent_mentions_name_rows: 6
- intent_source: {'llm': 7}
- secret_rows: 0
- abs_path_rows: 0
- schema_invalid_rows: 0
- expected_eq_input_rows: 0
- commit_groups: 4
- max_rows_per_commit: 2
- multi_unit_commit_rows: 6
- per_repo: {'aura-rl-sutton': 2, 'aura-aima': 2, 'aura-kernel-sink': 3}
- test: {'none': 7}
- prompt_chars: {'n': 7, 'min': 275, 'p50': 888, 'p90': 3290, 'max': 4893, 'mean': 1642.1}
- prompt_tokens_est: {'n': 7, 'min': 91, 'p50': 296, 'p90': 1096, 'max': 1631, 'mean': 547}
- target_tokens_est: {'n': 7, 'min': 93, 'p50': 130, 'p90': 218, 'max': 371, 'mean': 164.3}

## all (n=97)

- exact_dup_rows: 0
- near_dup_rows: 0
- conflict_rows: 0
- intent_shared_rows: 0
- intent_auto_line_rows: 0
- intent_violation_rows: 0
- intent_mentions_name_rows: 57
- intent_source: {'llm': 97}
- secret_rows: 0
- abs_path_rows: 0
- schema_invalid_rows: 0
- expected_eq_input_rows: 0
- commit_groups: 22
- max_rows_per_commit: 19
- multi_unit_commit_rows: 90
- per_repo: {'aura-rl-sutton': 42, 'aura-kernel-sink': 44, 'aura-aima': 11}
- test: {'none': 97}
- prompt_chars: {'n': 97, 'min': 260, 'p50': 1574, 'p90': 4360, 'max': 7720, 'mean': 2089.6}
- prompt_tokens_est: {'n': 97, 'min': 86, 'p50': 524, 'p90': 1453, 'max': 2573, 'mean': 696.2}
- target_tokens_est: {'n': 97, 'min': 81, 'p50': 191, 'p90': 537, 'max': 1108, 'mean': 276.9}

## Export gates

| gate | level | ok | value |
|---|---|---|---|
| train-nonempty | block | PASS | 59 |
| train-size>=200 | warn | FAIL | 59 |
| host-pinned+selftest | block | PASS | bc0401d5068d |
| schema-valid | block | PASS | 0 |
| train-all-keep-strict | block | PASS | {'KEEP': 59} |
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
| eval-nonempty | warn | PASS | 7 |
| closure-failure(context)<=10% | block | PASS | 0.038 |
| closure-failure(all)<=30% | warn | PASS | 0.076 |
| tested-share>=30% | warn | FAIL | 0.0 |
| max-rows-per-commit<=8 | block | PASS | 8 |

**Export allowed: yes**

