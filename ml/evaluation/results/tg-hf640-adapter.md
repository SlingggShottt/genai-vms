# TG evaluation — `tg-real` / `test` (32 samples)

Mean over samples with a 95 % bootstrap interval and n. mIoU is over the stages the truth or the answer has; boundary error is between consecutive true stages that the answer also has.

| method | mIoU | boundary error | frame accuracy | usable answers | s/sample |
|---|---|---|---|---|---|
| rules (detector timing, no model) | 0.537 (0.462–0.617, n=32) | 0.7 s (0.558–0.847, n=36) | 0.801 (0.759–0.842, n=32) | – | – |
| hf_local base + adapter tg/v1, frames as trained | 0.354 (0.284–0.425, n=32) | 2.79 s (1.898–3.919, n=24) | 0.61 (0.537–0.683, n=32) | 1.0 (1.0–1.0, n=32) | 4.67 |

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

## hf_local base + adapter tg/v1, frames as trained

| by | mIoU |
|---|---|
| abuse | 0.184 (nan–nan, n=1) |
| activity | 0.39 (0.308–0.475, n=24) |
| burglary | 0.101 (nan–nan, n=1) |
| fighting | 0.242 (0.167–0.317, n=2) |
| shoplifting | 0.304 (0.106–0.501, n=4) |
| 1 view | 0.248 (0.139–0.375, n=8) |
| 2 views | 0.392 (0.267–0.541, n=12) |
| 3 views | 0.387 (0.296–0.489, n=12) |
| dataset span | 0.62 (nan–nan, n=1) |
| human | 0.196 (0.108–0.288, n=6) |
| model draft (looked at the clip) | 0.3 (0.231–0.376, n=17) |
| model draft (rule only) | 0.556 (0.434–0.712, n=8) |

35 true boundaries were not in the answer; 0 gateway errors.
