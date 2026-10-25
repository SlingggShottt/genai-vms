# TG evaluation — `tg-real` / `test` (32 samples)

Mean over samples with a 95 % bootstrap interval and n. mIoU is over the stages the truth or the answer has; boundary error is between consecutive true stages that the answer also has.

| method | mIoU | boundary error | frame accuracy | usable answers | s/sample |
|---|---|---|---|---|---|
| rules (detector timing, no model) | 0.537 (0.462–0.617, n=32) | 0.7 s (0.558–0.847, n=36) | 0.801 (0.759–0.842, n=32) | – | – |
| Ollama qwen2.5vl:3b (zero-shot) | 0.322 (0.238–0.408, n=32) | 4.826 s (3.441–6.314, n=35) | 0.405 (0.322–0.484, n=22) | 0.688 (0.531–0.844, n=32) | 18.5 |

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

## Ollama qwen2.5vl:3b (zero-shot)

| by | mIoU |
|---|---|
| abuse | 0.601 (nan–nan, n=1) |
| activity | 0.33 (0.23–0.446, n=24) |
| burglary | 0.28 (nan–nan, n=1) |
| fighting | 0.144 (0.032–0.257, n=2) |
| shoplifting | 0.302 (0.117–0.534, n=4) |
| 1 view | 0.297 (0.165–0.449, n=8) |
| 2 views | 0.222 (0.138–0.306, n=12) |
| 3 views | 0.438 (0.274–0.619, n=12) |
| dataset span | 0.286 (nan–nan, n=1) |
| human | 0.249 (0.11–0.423, n=6) |
| model draft (looked at the clip) | 0.336 (0.192–0.492, n=17) |
| model draft (rule only) | 0.35 (0.309–0.388, n=8) |

24 true boundaries were not in the answer; 1 gateway errors.
