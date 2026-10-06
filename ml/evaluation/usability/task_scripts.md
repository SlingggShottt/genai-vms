# Task scripts

Four tasks, one per capability the system is meant to be judged on. Read the scenario aloud, hand
over the card, say nothing else. Start the timer when the participant touches the mouse; stop it at
success, at "I'm done" or at the time limit. Record success (1), partial (0.5) or fail (0), the time,
the number of wrong turns (a click that took them somewhere they did not mean to go), and each
time you had to help (and what you said).

Before each participant: run `make demo-refresh` the day before (the footage expires after a day),
log in as an operator account, close all tabs but the dashboard, and clear the assistant's history.
Think-aloud is welcome but optional: ask it of the first participants only, so their times are not
the benchmark.

## Task 1 — find footage (search)

**Scenario.** "A colleague says someone carrying a backpack walked past the car park camera this
afternoon. Find a moment that shows it and open the video at that moment."

**Success.** The participant runs a search that mentions a backpack (or a bag), picks a result from
the car-park camera (or says none matches) and reaches the playback page at that time.
**Limit.** 4 minutes. **Watch for.** Do they notice the fast/reason toggle? Do they open the result's
trace? Do they read the "N older matches hidden" note and understand it?

## Task 2 — handle an alert

**Scenario.** "An alert has just come in. Look at it, decide whether it is real, and mark it as
dealt with, leaving a note saying why."

**Success.** Opens the newest high-severity alert, looks at its keyframe or clip, acknowledges it and
resolves it with a note that gives a reason. **Limit.** 3 minutes. **Watch for.** Do they find the
tray or the Alerts page? Do they understand "verified by the vision model" versus "unverified"?

## Task 3 — ask the assistant

**Scenario.** "Your supervisor asks: how many people were on the waiting-room camera at the busiest
time on 4 October? Use the assistant to find out, then tell me where the number came from."

**Success.** Asks a question (any wording), reads the answer, and opens a cited record or the
"Records consulted" list to show where the figure came from. **Limit.** 4 minutes. **Watch for.**
Do they trust an answer with no source? Do they notice when the answer names the wrong day?

## Task 4 — read an incident report

**Scenario.** "A report was written for the incident in the car park. Find it, tell me in your own
words what happened and what the report recommends, then save it to a case called 'Review'."

**Success.** Opens the incident report, summarises it correctly (what, where, which stages), names at
least one recommended action and saves it to a case. **Limit.** 5 minutes. **Watch for.** Do they
click the evidence chips? Do they understand which statements the report is sure of (the
limitations section)?

## After the tasks

Hand over the SUS sheet (`sus_questionnaire.md`) before any discussion. Then ask the two open
questions and thank them. Record everything in `tasks.csv` and `sus.csv` (templates in this folder),
one row per task and one row per participant, with no names: `P01`, `P02`, ...
