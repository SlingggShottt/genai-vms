# TG evaluation — `tg-real` / `test` (32 samples)

Mean over samples with a 95 % bootstrap interval and n. mIoU is over the stages the truth or the answer has; boundary error is between consecutive true stages that the answer also has.

| method | mIoU | boundary error | frame accuracy | usable answers | s/sample |
|---|---|---|---|---|---|
| rules (detector timing, no model) | 0.537 (0.462–0.617, n=32) | 0.7 s (0.558–0.847, n=36) | 0.801 (0.759–0.842, n=32) | – | – |
| hf_local base (zero-shot, 4-bit), frames as trained | 0.274 (0.229–0.318, n=32) | 3.852 s (2.454–5.306, n=25) | 0.468 (0.407–0.526, n=23) | 0.719 (0.562–0.875, n=32) | 3.54 |

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

## hf_local base (zero-shot, 4-bit), frames as trained

| by | mIoU |
|---|---|
| abuse | 0.601 (nan–nan, n=1) |
| activity | 0.269 (0.221–0.316, n=24) |
| burglary | 0.563 (nan–nan, n=1) |
| fighting | 0.212 (0.167–0.257, n=2) |
| shoplifting | 0.18 (0.117–0.256, n=4) |
| 1 view | 0.288 (0.17–0.426, n=8) |
| 2 views | 0.311 (0.234–0.373, n=12) |
| 3 views | 0.228 (0.183–0.273, n=12) |
| dataset span | 0.286 (nan–nan, n=1) |
| human | 0.237 (0.144–0.38, n=6) |
| model draft (looked at the clip) | 0.278 (0.209–0.354, n=17) |
| model draft (rule only) | 0.291 (0.252–0.322, n=8) |

34 true boundaries were not in the answer; 0 gateway errors.
