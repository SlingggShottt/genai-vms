# Writing and labelling retrieval queries

For the person who adds queries to `queries.jsonl` (P4-J6). Read `queries.py` for the exact format;
this is how to fill it in so that the numbers mean something.

## What a query is

A sentence an operator would type, and a list of every place in the footage where the answer is.
The benchmark asks the system the sentence and checks whether the windows it returns land on those
places. A window counts when it overlaps a place by at least 2 seconds, on the same camera.

## The two kinds

**explicit** uses the words the thing is usually called: "a person gets into a car". **implicit**
describes it without them: "someone climbs into the driver's seat". Write both for as many things as
you can. Search that only matches words does well on explicit queries and badly on implicit ones,
which is the point of asking both.

The check is mechanical: `label` is what the ground truth calls the thing (`enter-vehicle`), and an
implicit query may not contain any of its words (`enter`, `vehicle`), so it cannot drift into an
explicit one by accident. `make_queries.py` and the runner both refuse a file that breaks it.

## The places

List **every** place the thing happens in the footage you search. A window that lands on a place you
forgot counts as wrong. If you are not sure you found them all, search a short, fully watched stretch
and say so in `note`.

Give a place as seconds on the recording's own clock (`start_s`, `end_s`: the benchmark lines the
clock up with the wall clock, see `meva_benchmark.calibrate`) or as absolute ISO times with a zone
(`start`, `end`). Mark the whole of the action, not a single frame: a place shorter than about 3 s is
easy to miss by a window and hard to score fairly.

## Filters

`filters.cameras` is what the operator would also have chosen on the page. The first configuration
of the ablation ignores it (to show what the filter is worth); the others use it. A place must be on
one of the filtered cameras.

## What makes a bad query

- One that two different things answer ("a person near a car"): list both as places, or do not ask.
- One whose answer depends on knowing who someone is, or on reading small text.
- One you only wrote after watching which windows came back.
- One copied from a sentence in the system's own captions: the system will find its own words.

## Adding queries

Add lines to `queries.jsonl` (or to `make_queries.py` for the MEVA examples stream), then
`uv run python ml/evaluation/retrieval/make_queries.py` checks the file, or
`uv run pytest ml/evaluation/retrieval/tests` does. Two people labelling the same ten queries
independently, and comparing, is the cheapest way to find the places nobody listed.
