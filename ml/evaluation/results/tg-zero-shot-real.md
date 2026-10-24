# TG evaluation — `tg-real` / `all` (196 samples)

Mean over samples with a 95 % bootstrap interval and n. mIoU is over the stages the truth or the answer has; boundary error is between consecutive true stages that the answer also has.

| method | mIoU | boundary error | frame accuracy | usable answers | s/sample |
|---|---|---|---|---|---|
| rules (detector timing, no model) | 0.468 (0.444–0.494, n=196) | 1.329 s (1.144–1.544, n=273) | 0.775 (0.757–0.793, n=196) | – | – |
| zero-shot qwen2.5vl:3b (16k context) | 0.349 (0.322–0.377, n=196) | 4.052 s (3.563–4.537, n=252) | 0.507 (0.472–0.543, n=125) | 0.638 (0.571–0.704, n=196) | 19.3 |

## rules (detector timing, no model)

| by | mIoU |
|---|---|
| abuse | 0.467 (0.334–0.601, n=2) |
| activity | 0.468 (0.44–0.498, n=137) |
| arrest | 0.642 (0.498–0.784, n=5) |
| assault | 0.589 (0.434–0.717, n=3) |
| burglary | 0.364 (0.299–0.429, n=13) |
| fighting | 0.411 (0.294–0.516, n=5) |
| robbery | 0.501 (0.423–0.588, n=5) |
| shoplifting | 0.48 (0.407–0.554, n=21) |
| vandalism | 0.468 (0.404–0.561, n=5) |
| 1 view | 0.468 (0.429–0.51, n=59) |
| 2 views | 0.446 (0.417–0.477, n=86) |
| 3 views | 0.506 (0.451–0.572, n=51) |
| dataset span | 0.347 (0.285–0.407, n=7) |
| human | 0.504 (0.445–0.565, n=29) |
| model draft (looked at the clip) | 0.523 (0.485–0.564, n=101) |
| model draft (rule only) | 0.372 (0.361–0.383, n=59) |

150 true boundaries were not in the answer; 0 gateway errors.

## zero-shot qwen2.5vl:3b (16k context)

| by | mIoU |
|---|---|
| abuse | 0.698 (0.601–0.795, n=2) |
| activity | 0.36 (0.326–0.394, n=137) |
| arrest | 0.281 (0.103–0.473, n=5) |
| assault | 0.238 (0.069–0.434, n=3) |
| burglary | 0.232 (0.16–0.318, n=13) |
| fighting | 0.214 (0.107–0.303, n=5) |
| robbery | 0.345 (0.196–0.533, n=5) |
| shoplifting | 0.388 (0.304–0.475, n=21) |
| vandalism | 0.314 (0.257–0.373, n=5) |
| 1 view | 0.323 (0.274–0.373, n=59) |
| 2 views | 0.36 (0.32–0.401, n=86) |
| 3 views | 0.36 (0.308–0.416, n=51) |
| dataset span | 0.346 (0.246–0.486, n=7) |
| human | 0.278 (0.223–0.338, n=29) |
| model draft (looked at the clip) | 0.37 (0.323–0.421, n=101) |
| model draft (rule only) | 0.348 (0.333–0.362, n=59) |

171 true boundaries were not in the answer; 11 gateway errors.
