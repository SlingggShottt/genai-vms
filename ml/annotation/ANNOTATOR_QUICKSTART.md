# Marking the phases of a clip: five-minute quickstart

You are marking **when each phase of what happens in a clip starts and ends**. The definitions and
worked examples are in `GUIDELINE.md`; this page is only about what to click.

## One clip

1. Open a project (`<your name> - 2 views` or `- 3 views`) and press **Label All Tasks**. Do one
   project to the end, then the other.
2. The title is the clip's id and what the clip is suggested to be. Below it are the clip's videos:
   the **first one is the one you mark**; the others show the same moment from other cameras. Use
   the play button under each video, or drag its own bar, to look at them.
3. Under the first video is a timeline with one row per phase (`baseline`, `precursor`,
   `escalation`, `action`, `aftermath`). **Each step on it is one second**, and the clip fits on the
   screen.
4. To mark a phase: click its name in the row of buttons under the videos, then **click and drag
   slowly along the timeline** from where the phase starts to where it ends. A coloured bar
   appears. Drag a bar's end to adjust it. To take back the last change, use the **undo arrow** at
   the bottom left (twice removes a bar you have just drawn and then moved).
5. Mark only the phases you can see. **Leave a phase out** if it is not in the clip; do not
   stretch a neighbour to cover the gap. Phases go in order and must not overlap; the next phase
   may start where the previous one ends (sharing one second is fine, it is snapped).
6. Answer the three questions below the buttons:
   - **Which view shows the incident best?** The camera where it is easiest to see, not
     necessarily the first.
   - **What kind of incident is this?** The suggestion is in the title. Change it only if it is
     plainly wrong. Most clips here are ordinary activities, so `activity` is usually right.
   - **Is this clip usable?** Choose **No** only if nothing relevant can be seen at all (blocked
     camera, nothing in frame). A hard clip is still usable.
7. Press **Submit**. It moves on to the next clip.

## Things to know

- **Mark what you can see, not what you know.** A phase starts at the first moment its behaviour
  is visible.
- The timeline works in whole seconds. That is a limit of the tool, so do not try to be finer: put
  the boundary at the second where the change first shows.
- Do not mark a phase shorter than about a second unless that is how long it really is.
- You can come back to a clip: open it from the list and press **Update** after changing it.
- **Do not talk to the other annotator about specific clips.** About 20 clips are given to both of
  you on purpose, to measure how well two careful people agree; discussing them spoils that.
- If a video does not play, or drawing a bar does nothing, note the clip's id and move on; tell
  the person who sent you the package.

## Hand in

After your first 5 clips, and again when you finish, run `./export.sh` and send
`export-<name>.json` (see `README.md`).
