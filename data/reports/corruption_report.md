# Corruption Report

| State | Retrieval Hit Rate | Mean Token F1 | Quality Gate | Freshness | Stale Ratio |
|---|---:|---:|---|---|---:|
| Baseline | 1.000 | 0.500 | PASS | PASS | 0.000 |
| Corrupted | 0.500 | 0.221 | False | True | 0.05 |
| Repaired | 1.000 | 0.500 | True | True | 0.0 |

## Quality Details

- Corrupted stale rows: 1 / 20
- Repaired stale rows: 0 / 24
- Corrupted quality gate: False
- Repaired quality gate: True
