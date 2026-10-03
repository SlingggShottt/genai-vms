# Phase annotation guideline (P3-D5)

> **Status: draft.** The phase taxonomy is adapted from MP-PVIR and **needs the project guide's approval**
> (`docs/design_architecture.md` section 8.2) before annotation starts. If the guide changes a definition,
> change it here, in `tools/annotation_kit/src/annotation_kit/phases.py`, and regenerate the labelling configs
> (`annotation-kit phase-config --out ml/annotation/phase`); a test fails if they drift.

## What you are doing

You watch a short clip of an incident and mark **when each phase of it happens**, on the video's timeline.
Those marks train the model that later finds the phases of real incidents by itself, so what matters is that
two careful people mark about the same thing. When in doubt, follow the rules below rather than your own taste.

For each clip you also say **which camera shows the incident best**, **what kind of incident it is**, and
**whether the clip is usable at all**.

## The five phases

Phases describe what is *visible in the scene*, in this order. Each happens at most once per clip, they do not
overlap, and any of them can be missing.

| Phase | It is | It starts when | It ends when | Not this |
|---|---|---|---|---|
| **baseline** | The normal scene before anything relevant | the clip starts | the first sign that is tied to what follows | ordinary activity that has nothing to do with the incident, even if it is dramatic |
| **precursor** | The first observable signs tied to the incident: approaching, watching, lingering, looking around | someone first behaves in a way that leads to the incident | it becomes likely that something will happen: the decision point | a person who is merely present |
| **escalation** | The build-up: the incident is now likely and the people involved are committing to it | the build-up is visible (reaching, gripping, positioning, raising voices) | the core act begins | a long, calm lead-up (that is precursor) |
| **action** | The core act itself | the act begins (climbing over, striking, taking, setting down and leaving) | the act is over | the aftermath of it |
| **aftermath** | What follows and how people respond | the act is over | the clip ends or the scene returns to normal | the act itself continuing |

### Rules that keep two people agreeing

1. **Mark what you can see, not what you know.** If the incident is only obvious in hindsight, the phases that
   come before it still start where a behaviour first becomes visible, not where you worked out why.
2. **Boundaries go at the first frame where the change is visible.** A phase starts at the first frame showing
   it, and the previous one ends at the same frame. Do not agonise over a frame or two: the tools tolerate a
   few frames of overlap, and agreement is measured on seconds, not frames.
3. **Leave a phase out if it is not there.** A clip that starts in the middle of the action has no baseline or
   precursor. Do not stretch a neighbour to cover the gap, and do not mark a phase just because it is expected.
4. **Gaps are fine, overlaps are not.** If nothing fits a stretch, leave it unmarked. If you mark an overlap
   larger than three frames the clip is rejected and comes back to you.
5. **One person's incident, many people's scene.** Phases follow the incident, not every person in view.
   Background activity does not start a phase.
6. **Phases are for the whole clip, all views.** The views are cut to the same moment, so one set of marks applies
   to every camera. Mark on the first video (the suggested primary view) and use the others to see what that
   camera cannot.
7. **Do not mark a phase shorter than about a second** unless that is genuinely how long it is (a snatch can be
   that fast). A string of tiny phases usually means you are marking people's movements, not phases.
8. **Do not rely on audio or on what you know about the dataset.** There is none.

### Choosing the primary view

The camera where the incident is **easiest to see and understand**: the people involved are in frame, large
enough, unobstructed. It is not necessarily the one where it starts, and not necessarily the one first in the
list. If two are equally good, keep the suggestion.

### Event type

The list has the incident types the system detects (`intrusion`, `loitering`, `crowding`, `abandoned_object`,
`running`), `theft`, the UCF-Crime classes, and `activity` for ordinary-activity episodes (MEVA). The clip
arrives with a suggestion; change it only if it is plainly wrong. Use the **most specific** type that fits.

### Usable?

Choose **No** if no incident can be seen in the clip: the camera is blocked or dark, the incident is out of frame
the whole time, the video is corrupt. Do not choose No because the clip is hard; hard clips are exactly what
is needed. A clip marked No is left out of the training data.

## Worked examples

These are *illustrative scenarios*, written to show where the lines go; they are not taken from the datasets.
Times are seconds into a clip.

### Intrusion

**1. Fence climb at night (single view, 45 s).**

| Phase | Seconds | What is visible |
|---|---|---|
| baseline | 0-9 | Empty yard, lit gate, a car passes on the road |
| precursor | 9-21 | A person walks along the outside of the fence, stops twice, looks toward the building |
| escalation | 21-27 | The person grips the top of the fence and glances at the guard hut |
| action | 27-36 | Climbs over and drops inside |
| aftermath | 36-45 | Walks across the yard toward the building, leaves the frame |

**2. Tailgating through a staff door (2 views, 30 s).**

| Phase | Seconds | What is visible |
|---|---|---|
| baseline | 0-6 | Corridor camera: a member of staff badges in |
| precursor | 6-11 | A second person waits close behind, not badging |
| escalation | 11-13 | The door starts to close and the second person reaches for it |
| action | 13-18 | Catches the door and enters |
| aftermath | 18-30 | Walks away from the door; the staff member turns and looks back |

*Marked on the corridor view; the lobby view shows the staff member noticing, which is why the corridor is
primary.*

**3. A restricted area entered openly (single view, 40 s).** No baseline: the clip begins as a person already
walks toward a "no entry" gate.

| Phase | Seconds | What is visible |
|---|---|---|
| precursor | 0-8 | Walks up to the gate, reads the sign |
| action | 8-15 | Pushes the gate open and walks in |
| aftermath | 15-40 | Continues inside; a guard enters the frame and approaches |

*No escalation: nothing builds between reading the sign and walking in. Do not invent one.*

### Loitering

**1. Waiting outside a shop (single view, 60 s).**

| Phase | Seconds | What is visible |
|---|---|---|
| baseline | 0-10 | Pedestrians pass normally |
| precursor | 10-30 | One person stops by the window and stays |
| escalation | 30-45 | Keeps looking up and down the street, checks the phone repeatedly, paces |
| action | 45-55 | Continues to stay in the same area (the loitering itself is the incident) |
| aftermath | 55-60 | A staff member comes out and speaks to the person |

*For loitering, the "act" is the sustained presence. It starts when staying has clearly become the behaviour,
not the moment they first stop.*

**2. Lingering at an ATM (2 views, 45 s).** Escalation begins when the person lets others go ahead of them
twice; action when they step to the machine and do nothing; aftermath when they walk off with a person who
arrives.

**3. Passing time at a school gate after hours (single view, 50 s).** Only baseline and precursor and action are
marked; the person leaves the frame, so there is no aftermath.

### Crowding

**1. A platform filling up (2 views, 60 s).**

| Phase | Seconds | What is visible |
|---|---|---|
| baseline | 0-12 | A few people spread along the platform |
| precursor | 12-25 | A train is announced; people start to gather near the doors |
| escalation | 25-40 | The group thickens; people press toward the edge |
| action | 40-52 | Crowded: people packed shoulder to shoulder at the doors |
| aftermath | 52-60 | Doors open, the crowd flows into the train and thins |

**2. A queue that spills into a walkway (single view, 55 s).** Baseline is a short orderly queue; precursor is
the queue lengthening; escalation is the end of the queue reaching the walkway; action is people having to step
around it; aftermath is the queue being split and moved on by staff.

**3. A crowd that forms and disperses (single view, 40 s).** Start the action when the density is at its
highest and stable, not when the first extra person arrives.

### Abandoned object

**1. A bag left on a bench (2 views, 50 s).**

| Phase | Seconds | What is visible |
|---|---|---|
| baseline | 0-10 | Station concourse, people passing |
| precursor | 10-20 | A person carrying a backpack stops by a bench and looks around |
| escalation | 20-25 | Sets the backpack down beside them, steps back |
| action | 25-31 | Walks away without it |
| aftermath | 31-50 | The bag sits alone; people pass; one looks at it |

*The primary view is the one that shows the person walking away.*

**2. A suitcase pushed against a wall (single view, 40 s).** Escalation is when the owner positions the case
against the wall; action when the owner leaves it and walks out of the owner's frame; aftermath when the case is
alone for the rest of the clip.

**3. A bag put down and picked up again (single view, 30 s).** The person returns for the bag at 24 s. Mark baseline,
precursor and action only up to that point, and **aftermath** as the return: the incident ended in a resolution,
not an abandoned bag. This is still an `abandoned_object` clip, because that is what it looked like for 20 s.

### Running

**1. A sprint across a car park (single view, 30 s).**

| Phase | Seconds | What is visible |
|---|---|---|
| baseline | 0-6 | Walkers cross the car park |
| precursor | 6-9 | One person looks back over their shoulder |
| escalation | 9-11 | Breaks into a jog |
| action | 11-19 | Runs flat out across the frame |
| aftermath | 19-30 | Slows to a walk, hands on knees, another person arrives |

**2. A person chased through a corridor (2 views, 25 s).** Escalation starts when the second person is seen in
pursuit; action begins when the first person is at full speed and ends when they leave the camera's view.

**3. Running for a bus (single view, 20 s).** No escalation and a very short precursor; do not stretch them.

### Theft (and the UCF-Crime classes)

`theft` covers shoplifting, stealing, burglary and robbery. The other UCF-Crime classes below are marked with
the same five phases; the wording of "action" changes, the rules do not.

**Shoplifting (single view, 50 s).** baseline 0-8 browsing; precursor 8-22 watches the counter and the staff;
escalation 22-30 hand moves toward the item, checks again; action 30-34 takes and conceals it; aftermath 34-50
leaves the store, staff look up.

**Burglary (2 views, 55 s).** precursor: tries a door handle; escalation: forces it; action: enters; aftermath:
comes out carrying a bag.

**Robbery (single view, 40 s).** precursor: approaches the cashier and waits; escalation: produces a threatening
gesture or object; action: the handover; aftermath: runs out, bystanders react.

**Fighting (single view, 35 s).** precursor: raised voices and gestures; escalation: pushing; action: striking
and grappling; aftermath: separated, one person on the ground, others come over.

**Assault (single view, 30 s).** Often no baseline. precursor: the attacker follows the victim; escalation:
closes in; action: the blow; aftermath: the attacker leaves and the victim stays.

**Abuse (single view, 60 s).** Phases can be long and quiet. precursor: the carer and the person in their care
interact normally for a while; escalation: the first rough handling; action: the abuse; aftermath: the carer
leaves or composes themselves.

**Arrest (single view, 45 s).** precursor: officers approach; escalation: the person is told to stop and
resists; action: restrained and cuffed; aftermath: led away.

**Vandalism (single view, 40 s).** precursor: looks around and picks up an object; escalation: raises it; action:
the damage; aftermath: runs off, damage visible.

### MEVA activity episodes (`activity`)

MEVA is everyday activity, not incidents, so the "incident" is an *episode* with a beginning, a middle and an
end. The phases still apply: where the episode has no real escalation, leave it out.

**1. A vehicle drops someone off (3 views, 40 s).** baseline: the road is quiet; precursor: a car slows and
pulls in; escalation: it stops and the door opens; action: the passenger gets out and walks away; aftermath:
the car pulls off.

**2. A vehicle picks someone up (2 views, 40 s).** The mirror image: precursor is the person waiting and looking
up the road; action is getting in.

**3. An object changes hands (3 views, 20 s).** Short: baseline is two people walking toward each other; action
is the handover; aftermath is them walking apart. Precursor and escalation are usually absent.

## Where the clips come from

- **UCF-Crime**: eight classes, **abuse, arrest, assault, burglary, fighting, robbery, shoplifting, vandalism**.
  Chosen because each has a visible approach, build-up, act and response, and because they are the violent and
  theft incidents the event rules and incident reports are about. The other five (arson, explosion, road
  accidents, shooting, stealing) either have no scene to phase (an explosion has no approach) or are covered by a
  class kept here. Single view. *(Not yet checked against the downloaded files.)*
- **MEVA**: the only source of time-synchronised **multi-view** footage. MEVA is not an incident dataset: in
  the released annotations abandoned packages appear in 1 clip and thefts in 4, neither with a second
  synchronised view, and there is no intrusion, loitering, crowding or running. So the clips are everyday
  activity episodes with a clear beginning and end (vehicle drop-offs and pick-ups, object transfers, embraces,
  loading and unloading, carrying, cycling). On the released annotations this gives 361 candidate episodes from
  179 five-minute slots (2,131 before near-duplicates are capped), from which a few hundred are annotated.
  Whether a drop-off counts as an "incident" worth training on is a judgement for the team and the guide; the
  extraction is configurable.

## Running the pipeline

```bash
# candidates (MEVA needs a checkout of https://gitlab.kitware.com/meva/meva-data-repo)
uv run annotation-kit meva-candidates --repo <meva-data-repo> --out meva_candidates.json
uv run annotation-kit ucf-candidates --videos <dir> --annotations <Temporal_Anomaly...txt> --out ucf_candidates.json

# cut every view to the same moment (a script to review, or --run)
uv run annotation-kit cut meva_candidates.json --out-dir clips \
    --source-prefix s3://mevadata-public-01/=/data/meva/ --script cut_clips.sh

# Label Studio: one project per number of views
uv run annotation-kit phase-config --out ml/annotation/phase
uv run annotation-kit phase-tasks meva_candidates.json --clip-prefix s3://vms-evidence/clips/ --out-dir tasks

# after annotating: Export > JSON, then
uv run annotation-kit phase-convert export.json --out phase_labels.jsonl
```

In Label Studio, create a project per number of views (`tasks_<n>view(s).json` with
`phase_labelling_<n>view(s).xml`), paste the config under *Labeling Setup > Custom template*, and import the tasks.
Clips are cut at a constant 30 fps so that Label Studio's frame numbers convert to seconds exactly.

## Agreement

Before annotating the rest, **K and P both label the same 20 clips**. Then:

```bash
uv run annotation-kit phase-agreement k.jsonl p.jsonl
```

reports, per phase, the IoU between the two annotators' marks and whether they agree the phase happens, plus
mIoU, boundary difference, frame-wise agreement with Cohen's kappa, and which clips they disagreed on most.
**Read the clips they disagreed on together** before looking at a number. Low agreement on one phase is a problem
with its definition in this guideline, not with an annotator: rewrite the definition and relabel. A reasonable
bar to agree with the guide is mIoU of at least 0.6 and no phase below 0.4; neither figure is a result of this
project, they are starting points.
