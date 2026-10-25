# TG evaluation — `tg-real` / `test` (32 samples)

Mean over samples with a 95 % bootstrap interval and n. mIoU is over the stages the truth or the answer has; boundary error is between consecutive true stages that the answer also has.

| method | mIoU | boundary error | frame accuracy | usable answers | s/sample |
|---|---|---|---|---|---|
| rules (detector timing, no model) | 0.537 (0.462–0.617, n=32) | 0.7 s (0.558–0.847, n=36) | 0.801 (0.759–0.842, n=32) | – | – |
| hf_local base + adapter tg/v1 | 0.39 (0.318–0.469, n=32) | 2.419 s (1.623–3.467, n=26) | 0.656 (0.587–0.728, n=32) | 1.0 (1.0–1.0, n=32) | 3.06 |

## rules (detector timing, no model)

| by | mIoU |
|---|---|
| abuse | 0.601 (nan–nan, n=1) |
| activity | 0.535 (0.443–0.64, n=24) |
| burglary | 0.563 (nan–nan, n=1) |
| fighting | 0.532 (0.49–0.573, n=2) |
| shoplifting | 0.525 (0.343–0.707, n=4) |
| 1 view | 0.541 (0.446–0.636, n=8) |
| 2 views | 0.407 (0.36–0.452, n=12) |
| 3 views | 0.663 (0.499–0.825, n=12) |
| dataset span | 0.342 (nan–nan, n=1) |
| human | 0.564 (0.457–0.664, n=6) |
| model draft (looked at the clip) | 0.612 (0.487–0.738, n=17) |
| model draft (rule only) | 0.381 (0.351–0.409, n=8) |

23 true boundaries were not in the answer; 0 gateway errors.

## hf_local base + adapter tg/v1

| by | mIoU |
|---|---|
| abuse | 0.664 (nan–nan, n=1) |
| activity | 0.415 (0.333–0.5, n=24) |
| burglary | 0.101 (nan–nan, n=1) |
| fighting | 0.27 (0.222–0.317, n=2) |
| shoplifting | 0.304 (0.106–0.501, n=4) |
| 1 view | 0.315 (0.176–0.47, n=8) |
| 2 views | 0.417 (0.278–0.572, n=12) |
| 3 views | 0.412 (0.323–0.506, n=12) |
| dataset span | 0.62 (nan–nan, n=1) |
| human | 0.206 (0.113–0.296, n=6) |
| model draft (looked at the clip) | 0.333 (0.265–0.414, n=17) |
| model draft (rule only) | 0.619 (0.498–0.757, n=8) |

33 true boundaries were not in the answer; 0 gateway errors.
