125 of 196 samples got a usable answer from the model (64%); 11 calls failed outright.

On those 125 answers alone: model mIoU **0.273**, rules on the same clips **0.46**; the model was better on 22, worse on 103, equal on 0.

Stages the model ever said: {'action': 195, 'aftermath': 135, 'baseline': 358, 'precursor': 55}. True stages on the same clips: {'action': 279, 'aftermath': 216, 'baseline': 172, 'escalation': 9, 'precursor': 67}.

| frames shown | no usable answer |
|---|---|
| 5 | 4/54 |
| 6 | 5/47 |
| 7 | 18/41 |
| 8 | 44/54 |

| labels made by | answered clips | model | rules |
|---|---|---|---|
| dataset span | 7 | 0.346 | 0.347 |
| human | 23 | 0.234 | 0.519 |
| model draft (looked at the clip) | 63 | 0.247 | 0.492 |
| model draft (rule only) | 32 | 0.334 | 0.379 |

| exact source | answered clips | model | rules |
|---|---|---|---|
| dataset-span:ucf-crime | 7 | 0.346 | 0.347 |
| draft:frames | 19 | 0.333 | 0.44 |
| draft:padding-rule | 32 | 0.334 | 0.379 |
| draft:zoomed-frames | 44 | 0.21 | 0.515 |
| human:accepted-draft | 15 | 0.269 | 0.532 |
| human:corrected-draft | 2 | 0.189 | 0.462 |
| human:from-scratch | 6 | 0.161 | 0.506 |
