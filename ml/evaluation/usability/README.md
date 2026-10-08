# Usability kit (P7-J5)

For the study with five or more participants (the backlog asks for at least eight): a SUS
questionnaire, four task scripts, a consent note and result templates, plus a scorer.

| File | For |
|---|---|
| `consent_note.md` | read out / handed over before a session |
| `task_scripts.md` | the four tasks (search, handle an alert, ask the assistant, read an incident report): wording, what counts as success, what to record |
| `sus_questionnaire.md` | the ten items, after the tasks |
| `tasks_template.csv`, `sus_template.csv` | one row per participant and task; one row per participant |
| `sus.py` | scores the two CSVs |

```bash
uv run python ml/evaluation/usability/sus.py --sus sus.csv --tasks tasks.csv --out usability-results.md
```

SUS per participant (odd items answer − 1, even items 5 − answer, sum × 2.5); the group mean with a 95 %
bootstrap interval, range and the usual adjective band; per task the success rate (1, 0.5 or 0), fully
completed, median time, wrong turns and how many needed help. With fewer than five participants the
report says it is a first impression, not a measurement. A row with a missing or out-of-range answer
stops the run and names the participant instead of being guessed.

No session has been held: there are no results yet. Tests: `uv run pytest ml/evaluation/usability`.
