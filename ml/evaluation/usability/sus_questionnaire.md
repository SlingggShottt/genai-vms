# System Usability Scale (SUS)

Give this to each participant **after** the last task and **before** any discussion. One sheet per
participant; they answer all ten items by circling one number from 1 (strongly disagree) to 5
(strongly agree). Do not help with the wording; if an item does not apply, ask for a best guess.

The ten items are John Brooke's original SUS (1986); the scale is free to use with attribution.
"The system" means the GenAI-VMS web application they just used.

| # | Statement | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|---|
| 1 | I think that I would like to use this system frequently. | ○ | ○ | ○ | ○ | ○ |
| 2 | I found the system unnecessarily complex. | ○ | ○ | ○ | ○ | ○ |
| 3 | I thought the system was easy to use. | ○ | ○ | ○ | ○ | ○ |
| 4 | I think that I would need the support of a technical person to be able to use this system. | ○ | ○ | ○ | ○ | ○ |
| 5 | I found the various functions in this system were well integrated. | ○ | ○ | ○ | ○ | ○ |
| 6 | I thought there was too much inconsistency in this system. | ○ | ○ | ○ | ○ | ○ |
| 7 | I would imagine that most people would learn to use this system very quickly. | ○ | ○ | ○ | ○ | ○ |
| 8 | I found the system very cumbersome to use. | ○ | ○ | ○ | ○ | ○ |
| 9 | I felt very confident using the system. | ○ | ○ | ○ | ○ | ○ |
| 10 | I needed to learn a lot of things before I could get going with this system. | ○ | ○ | ○ | ○ | ○ |

Then two open questions, answered in a sentence or two:

- What was the most confusing or frustrating moment?
- What did the system do that you would not want to lose?

**Scoring** (`sus.py`): odd items score (answer − 1), even items score (5 − answer); add the ten and
multiply by 2.5, giving 0–100. It is not a percentage. About 68 is the average over many studies; a
score is meaningful across a group of participants, not for one person.
