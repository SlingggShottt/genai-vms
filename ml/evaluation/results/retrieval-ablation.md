# Retrieval ablation — local profile, 2026-10-27 14:35 UTC

50 queries (20 implicit) on camera `meva-ex`; a result is relevant when it overlaps a relevant place by at least 2 s. R@k: a relevant window in the first k. mAP: average precision with the places as items (AP@10). tIoU@t: the first window's temporal IoU with a place is at least t.

| configuration | queries | R@1 | R@5 | R@10 | mAP | tIoU@0.3 | tIoU@0.5 | median s |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| embed | 50 | 0.02 | 0.10 | 0.12 | 0.02 | 0.02 | 0.00 | 0.33 |
| embed+filters | 50 | 0.04 | 0.16 | 0.22 | 0.04 | 0.04 | 0.04 | 0.31 |
| +rerank | 50 | 0.04 | 0.16 | 0.24 | 0.05 | 0.02 | 0.00 | 31.42 |
| +jit | 12 | 0.08 | 0.25 | 0.33 | 0.12 | 0.08 | 0.00 | 49.76 |

## Explicit and implicit queries apart

| configuration | kind | n | R@1 | R@5 | R@10 | mAP |
|---|---|---:|---:|---:|---:|---:|
| embed | explicit | 30 | 0.03 | 0.10 | 0.13 | 0.02 |
| embed | implicit | 20 | 0.00 | 0.10 | 0.10 | 0.02 |
| embed+filters | explicit | 30 | 0.07 | 0.17 | 0.20 | 0.03 |
| embed+filters | implicit | 20 | 0.00 | 0.15 | 0.25 | 0.05 |
| +rerank | explicit | 30 | 0.03 | 0.20 | 0.23 | 0.04 |
| +rerank | implicit | 20 | 0.05 | 0.10 | 0.25 | 0.07 |
| +jit | explicit | 7 | 0.00 | 0.29 | 0.29 | 0.05 |
| +jit | implicit | 5 | 0.20 | 0.20 | 0.40 | 0.21 |

## Latency per stage (median / p95, ms)

| configuration | encode | fuse | plan | rerank | retrieve | total |
|---|---:|---:|---:|---:|---:|---:|
| embed | 69 / 119 | 228 / 467 | 0 / 0 | – | 35 / 117 | 324 / 654 |
| embed+filters | 64 / 76 | 224 / 248 | 0 / 0 | – | 22 / 27 | 310 / 341 |
| +rerank | 190 / 524 | 247 / 518 | 5149 / 11634 | 22413 / 34219 | 68 / 175 | 31307 / 43539 |
| +jit | 356 / 389 | 232 / 280 | 3078 / 3673 | 45759 / 49276 | 58 / 76 | 49323 / 53022 |

## `+rerank` and `+jit` on the same queries

| configuration | n | R@1 | R@5 | R@10 | mAP |
|---|---:|---:|---:|---:|---:|
| +rerank | 12 | 0.08 | 0.25 | 0.33 | 0.12 |
| +jit | 12 | 0.08 | 0.25 | 0.33 | 0.12 |
