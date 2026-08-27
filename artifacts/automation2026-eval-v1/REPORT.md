# AutoCtrl Parser-only Reference Evaluation

> This is a parser-only run on 320 utterances with author-generated labels.
> Independent dual-annotator review remains required before conference submission.

## Safety boundary

The evaluator imported no `rclpy`, created no ROS node or publisher, and sent no
`/cmd_vel` messages. Only text interpretation was measured.

## Run metadata

- Timestamp: `2026-08-27T14:42:02+08:00`
- Model: `qwen3.6:35b`
- Model digest: `07d35212591fc27746f0a317c975a6d68754fb38e9053d82e25f06057af28522`
- Ollama version: `0.23.4`
- Dataset: `tests/corpus/commands_320.csv`
- Dataset SHA-256: `0747f1777e22668ca9c2e289449334030fb6d93f76db7d0f539d77774052ffa4`
- uv.lock SHA-256: `061a0b5b1d836222d550fd9485b3d8684fe9ad5b977abff417b6038aefe014af`
- Evaluator SHA-256: `a9fd4e547b74dea5fdb033c90833dab635fe75a95d01a7ce1ed33ce2c89f1888`
- Cases: `320`
- Git commit: `afd4aba3ea910a78e186328f5c706882d3d551e7` (dirty: `False`)
- ROS imported: `False`
- Model sampling: temperature `0.0`, seed `42`; one observation per utterance

## Overall results

| Baseline | Request-class accuracy | Exact request | Motion intent | Requested slots | Status | No-tool | Potential false nonzero selection | P50 | P95 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| rule-only | 70.9% (227/320) | 70.6% (226/320) | 63.1% (111/176) | 67.2% (43/64) | 64.1% (41/64) | 92.5% (74/80) | 1.2% (2/160) | 0.0 ms | 0.0 ms |
| llm-only | 95.3% (305/320) | 94.4% (302/320) | 97.2% (171/176) | 100.0% (64/64) | 100.0% (64/64) | 87.5% (70/80) | 2.5% (4/160) | 1264.4 ms | 1719.7 ms |
| hybrid-v0 | 93.1% (298/320) | 87.5% (280/320) | 96.6% (170/176) | 76.6% (49/64) | 92.2% (59/64) | 83.8% (67/80) | 5.0% (8/160) | 0.0 ms | 1708.5 ms |
| guarded-hybrid | 94.1% (301/320) | 93.4% (299/320) | 96.0% (169/176) | 100.0% (64/64) | 95.3% (61/64) | 87.5% (70/80) | 3.8% (6/160) | 0.1 ms | 1699.2 ms |

## Exact accuracy by category

| Category | rule-only | llm-only | hybrid-v0 | guarded-hybrid |
|---|---:|---:|---:|---:|
| ambiguous | 84.4% (27/32) | 68.8% (22/32) | 62.5% (20/32) | 71.9% (23/32) |
| canonical_motion | 91.7% (44/48) | 100.0% (48/48) | 100.0% (48/48) | 100.0% (48/48) |
| conversation | 97.9% (47/48) | 100.0% (48/48) | 97.9% (47/48) | 97.9% (47/48) |
| long_tail_motion | 37.5% (24/64) | 87.5% (56/64) | 89.1% (57/64) | 87.5% (56/64) |
| parameterized_motion | 67.2% (43/64) | 100.0% (64/64) | 76.6% (49/64) | 100.0% (64/64) |
| status | 64.1% (41/64) | 100.0% (64/64) | 92.2% (59/64) | 95.3% (61/64) |

## Interpretation notes

- `rule-only` uses the production deterministic motion/status paths and returns no-tool when unmatched.
- `llm-only` sends every utterance directly to the local Ollama model.
- `hybrid-v0` is the original unguarded deterministic-first router.
- `guarded-hybrid` is the production router: only high-confidence deterministic matches bypass the local model.
- Exact-request accuracy requires request class, kind, direction, and all supplied numeric slots to match. Wilson 95% intervals and paired exact McNemar tests are available in the CSV outputs.
- Potential false nonzero selection counts a predicted move/rotate for status, no-tool, or stop cases. Because the evaluator creates no ROS publisher, this is a parser-risk proxy rather than observed physical actuation.
- Latency excludes model warm-up and ROS execution; it measures interpretation only.
