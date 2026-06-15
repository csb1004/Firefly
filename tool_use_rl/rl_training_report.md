# RL Tool Selector Training Report

- Model: `standard-library contextual-bandit q-learning tool selector`
- Training rows: 3500
- Validation rows: 1000
- Test rows: 500
- Actions: 101

## Validation Metrics

| Metric | Value |
| --- | ---: |
| Top-1 Accuracy | 63.40% |
| Top-3 Accuracy | 76.50% |
| Sequence Accuracy | 47.20% |
| Multi-Tool Accuracy | 1.20% |
| Ambiguous Query Accuracy | 6.00% |
| Context-dependent Accuracy | 100.00% |
| Average Reward | 35.80% |
| Evaluated Rows | 1000 |

## Test Metrics

| Metric | Value |
| --- | ---: |
| Top-1 Accuracy | 84.00% |
| Top-3 Accuracy | 100.00% |
| Sequence Accuracy | 49.60% |
| Multi-Tool Accuracy | 1.60% |
| Ambiguous Query Accuracy | 0.00% |
| Context-dependent Accuracy | 100.00% |
| Average Reward | 77.45% |
| Evaluated Rows | 500 |

## Last Episodes

| Episode | Epsilon | Train Avg Reward | Validation Avg Reward | Validation Sequence Accuracy |
| ---: | ---: | ---: | ---: | ---: |
| 21 | 0.1359 | 28.69% | 0.00% | 0.00% |
| 22 | 0.1319 | 26.29% | 0.00% | 0.00% |
| 23 | 0.1279 | 29.03% | 0.00% | 0.00% |
| 24 | 0.1241 | 28.29% | 0.00% | 0.00% |
| 25 | 0.1204 | 28.30% | 0.00% | 0.00% |
| 26 | 0.1167 | 29.46% | 0.00% | 0.00% |
| 27 | 0.1132 | 29.61% | 0.00% | 0.00% |
| 28 | 0.1098 | 29.05% | 0.00% | 0.00% |
| 29 | 0.1065 | 31.32% | 0.00% | 0.00% |
| 30 | 0.1034 | 31.41% | 35.80% | 47.20% |
