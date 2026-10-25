# TG evaluation — `tg-real` / `test` (32 samples)

Mean over samples with a 95 % bootstrap interval and n. mIoU is over the stages the truth or the answer has; boundary error is between consecutive true stages that the answer also has.

| method | mIoU | boundary error | frame accuracy | usable answers | s/sample |
|---|---|---|---|---|---|
| rules (detector timing, no model) | 0.537 (0.462–0.617, n=32) | 0.7 s (0.558–0.847, n=36) | 0.801 (0.759–0.842, n=32) | – | – |
| hf_local base (zero-shot, 4-bit) | 0.335 (0.258–0.421, n=32) | 4.764 s (3.491–6.121, n=28) | 0.471 (0.405–0.536, n=25) | 0.781 (0.625–0.906, n=32) | 2.28 |

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

## hf_local base (zero-shot, 4-bit)

| by | mIoU |
|---|---|
| abuse | 0.288 (nan–nan, n=1) |
| activity | 0.366 (0.273–0.474, n=24) |
| burglary | 0.123 (nan–nan, n=1) |
| fighting | 0.162 (0.114–0.209, n=2) |
| shoplifting | 0.302 (0.117–0.534, n=4) |
| 1 view | 0.243 (0.147–0.379, n=8) |
| 2 views | 0.288 (0.207–0.364, n=12) |
| 3 views | 0.445 (0.284–0.626, n=12) |
| dataset span | 0.286 (nan–nan, n=1) |
| human | 0.228 (0.12–0.404, n=6) |
| model draft (looked at the clip) | 0.38 (0.244–0.533, n=17) |
| model draft (rule only) | 0.328 (0.293–0.361, n=8) |

31 true boundaries were not in the answer; 0 gateway errors.
