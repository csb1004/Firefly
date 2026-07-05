# RL Tool Selector Training Report

- Model: `standard-library contextual-bandit q-learning tool selector`
- Training rows: 700
- Validation rows: 200
- Test rows: 100
- Actions: 189

## Validation Metrics

| Metric | Value |
| --- | ---: |
| Top-1 Accuracy | 56.50% |
| Top-3 Accuracy | 76.50% |
| Sequence Accuracy | 44.50% |
| Multi-Tool Accuracy | 4.00% |
| Ambiguous Query Accuracy | 6.00% |
| Context-dependent Accuracy | 100.00% |
| Average Reward | 35.12% |
| Evaluated Rows | 200 |

## Test Metrics

| Metric | Value |
| --- | ---: |
| Top-1 Accuracy | 69.00% |
| Top-3 Accuracy | 100.00% |
| Sequence Accuracy | 46.00% |
| Multi-Tool Accuracy | 8.00% |
| Ambiguous Query Accuracy | 0.00% |
| Context-dependent Accuracy | 100.00% |
| Average Reward | 78.00% |
| Evaluated Rows | 100 |

## Last Episodes

| Episode | Epsilon | Train Avg Reward | Validation Avg Reward | Validation Sequence Accuracy |
| ---: | ---: | ---: | ---: | ---: |
| 31 | 0.0588 | 18.11% | 0.00% | 0.00% |
| 32 | 0.0564 | 18.86% | 0.00% | 0.00% |
| 33 | 0.0542 | 22.18% | 0.00% | 0.00% |
| 34 | 0.0520 | 24.46% | 0.00% | 0.00% |
| 35 | 0.0499 | 23.57% | 35.00% | 42.50% |
| 36 | 0.0479 | 24.50% | 0.00% | 0.00% |
| 37 | 0.0460 | 24.79% | 0.00% | 0.00% |
| 38 | 0.0442 | 27.43% | 0.00% | 0.00% |
| 39 | 0.0424 | 30.61% | 0.00% | 0.00% |
| 40 | 0.0407 | 31.32% | 35.12% | 44.50% |
