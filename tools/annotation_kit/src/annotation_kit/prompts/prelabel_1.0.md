You are helping to label security-camera footage. You are shown one phase of an incident, seen from one camera.

Event type: $event_type
Camera view: $view
Phase: $phase - $phase_definition
Time span: $start_s s to $end_s s of the clip

Describe only what is visible in this camera's view during this phase. Do not guess who anyone is or what they intend, and do not describe other phases or other cameras. If something cannot be seen, answer "Cannot tell" rather than guessing.

Write:
1. "caption": one or two sentences saying what people and objects do in this view during this phase.
2. "answers": an answer to every question below, using exactly one of the answers listed for it.

Questions:
$questions

Reply with JSON only, in this shape:
{"caption": "...", "answers": {"<question id>": "<answer>", "<question id>": "<answer>"}}
