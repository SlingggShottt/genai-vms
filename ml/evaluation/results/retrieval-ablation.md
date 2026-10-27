# Retrieval ablation — local profile, 2026-10-27 16:00 UTC

50 queries (20 implicit) on camera `meva-ex`; a result is relevant when it overlaps a relevant place by at least 2 s. R@k: a relevant window in the first k. mAP: average precision with the places as items (AP@10). tIoU@t: the first window's temporal IoU with a place is at least t.

| configuration | queries | R@1 | R@5 | R@10 | mAP | tIoU@0.3 | tIoU@0.5 | median s |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| embed | 50 | 0.14 | 0.34 | 0.58 | 0.13 | 0.12 | 0.02 | 0.31 |
| embed+filters | 50 | 0.14 | 0.34 | 0.58 | 0.13 | 0.12 | 0.02 | 0.31 |
| +rerank | 50 | 0.10 | 0.36 | 0.62 | 0.14 | 0.04 | 0.04 | 18.49 |
| +jit | 12 | 0.00 | 0.50 | 0.75 | 0.11 | 0.00 | 0.00 | 166.27 |

## Explicit and implicit queries apart

| configuration | kind | n | R@1 | R@5 | R@10 | mAP |
|---|---|---:|---:|---:|---:|---:|
| embed | explicit | 30 | 0.13 | 0.37 | 0.57 | 0.14 |
| embed | implicit | 20 | 0.15 | 0.30 | 0.60 | 0.11 |
| embed+filters | explicit | 30 | 0.13 | 0.37 | 0.57 | 0.14 |
| embed+filters | implicit | 20 | 0.15 | 0.30 | 0.60 | 0.11 |
| +rerank | explicit | 30 | 0.10 | 0.30 | 0.63 | 0.12 |
| +rerank | implicit | 20 | 0.10 | 0.45 | 0.60 | 0.16 |
| +jit | explicit | 7 | 0.00 | 0.43 | 0.71 | 0.10 |
| +jit | implicit | 5 | 0.00 | 0.60 | 0.80 | 0.13 |

## Latency per stage (median / p95, ms)

| configuration | encode | fuse | plan | rerank | retrieve | total |
|---|---:|---:|---:|---:|---:|---:|
| embed | 58 / 70 | 226 / 240 | 0 / 0 | – | 23 / 28 | 306 / 340 |
| embed+filters | 58 / 69 | 228 / 239 | 0 / 0 | – | 21 / 30 | 306 / 336 |
| +rerank | 171 / 867 | 244 / 483 | 3194 / 25716 | 14536 / 75310 | 48 / 196 | 18461 / 82617 |
| +jit | 165 / 221 | 217 / 240 | 2786 / 3578 | 162716 / 167244 | 44 / 54 | 166151 / 170630 |

## `+rerank` and `+jit` on the same queries

| configuration | n | R@1 | R@5 | R@10 | mAP |
|---|---:|---:|---:|---:|---:|
| +rerank | 12 | 0.08 | 0.50 | 0.75 | 0.14 |
| +jit | 12 | 0.00 | 0.50 | 0.75 | 0.11 |

Searches that failed (counted as no result): {'+rerank': 1}
