import { DEFAULT_TOLERANCE_S, MAX_TOLERANCE_S, MAX_TRANSIT_S } from './schemas';

/** What the camera-link form edits. Numbers are held as the text typed, so a half-typed "1."
 * isn't rewritten under the cursor; they are parsed when checked and when sent.
 */
export function newLinkDraft() {
  return {
    from: '',
    to: '',
    type: 'overlap',
    tolerance: String(DEFAULT_TOLERANCE_S),
    min: '',
    max: '',
    both: false,
  };
}

const text = (value) => (value === null || value === undefined ? '' : String(value));

export function draftFromEdge(edge) {
  return {
    from: edge.from_camera_id,
    to: edge.to_camera_id,
    type: edge.edge_type,
    tolerance: text(edge.tolerance_s ?? DEFAULT_TOLERANCE_S),
    min: text(edge.min_s),
    max: text(edge.max_s),
    both: edge.bidirectional,
  };
}

/** A number from what was typed; `null` for blank or anything that isn't one. */
export function parseSeconds(value) {
  if (typeof value !== 'string' || value.trim() === '') return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function checkSeconds(value, { label, max }) {
  const seconds = parseSeconds(value);
  if (seconds === null) return `Enter ${label} in seconds.`;
  if (seconds < 0 || seconds > max)
    return `${label[0].toUpperCase()}${label.slice(1)} must be between 0 and ${max} seconds.`;
  return undefined;
}

/** Problems with the draft, by field, as messages that say what to fix. These are the api's own
 * rules (services/api/src/api/domain/topology.py). `editing` skips the cameras: they can't change.
 */
export function linkProblems(draft, { editing = false } = {}) {
  const problems = {};
  if (!editing) {
    if (!draft.from) problems.from = 'Choose the first camera.';
    if (!draft.to) problems.to = 'Choose the second camera.';
    if (draft.from && draft.to && draft.from === draft.to) {
      problems.to = 'Choose two different cameras.';
    }
  }
  if (draft.type === 'overlap') {
    const message = checkSeconds(draft.tolerance, {
      label: 'the time tolerance',
      max: MAX_TOLERANCE_S,
    });
    if (message) problems.tolerance = message;
  } else {
    const min = checkSeconds(draft.min, { label: 'the shortest trip', max: MAX_TRANSIT_S });
    const max = checkSeconds(draft.max, { label: 'the longest trip', max: MAX_TRANSIT_S });
    if (min) problems.min = min;
    if (max) problems.max = max;
    if (!min && !max && parseSeconds(draft.max) < parseSeconds(draft.min)) {
      problems.max = 'The longest trip can’t be shorter than the shortest.';
    }
  }
  return problems;
}

export const canSaveLink = (draft, options) =>
  Object.keys(linkProblems(draft, options)).length === 0;

/** The body for POST /topology/edges. An overlap link is always two-way, so it sends no direction. */
export function draftToCreatePayload(draft) {
  const base = { from_camera_id: draft.from, to_camera_id: draft.to, edge_type: draft.type };
  if (draft.type === 'overlap') return { ...base, tolerance_s: parseSeconds(draft.tolerance) };
  return {
    ...base,
    min_s: parseSeconds(draft.min),
    max_s: parseSeconds(draft.max),
    bidirectional: draft.both,
  };
}

/** The body for PATCH /topology/edges/{id}: only what the edge's type has. */
export function draftToUpdatePayload(draft) {
  if (draft.type === 'overlap') return { tolerance_s: parseSeconds(draft.tolerance) };
  return {
    min_s: parseSeconds(draft.min),
    max_s: parseSeconds(draft.max),
    bidirectional: draft.both,
  };
}

const seconds = (value) => `${Number(value.toFixed(2))}`;

/** "±5 s" for an overlap, "10–45 s" for a transit. */
export function describeTiming(edge) {
  if (edge.edge_type === 'overlap') return `±${seconds(edge.tolerance_s ?? DEFAULT_TOLERANCE_S)} s`;
  return `${seconds(edge.min_s ?? 0)}–${seconds(edge.max_s ?? 0)} s`;
}

/** "cam01 ↔ cam02" when it works both ways, "cam01 → cam02" when it doesn't. `labelOf` turns a
 * camera id into what to show (its code); an unknown camera shows as "unknown camera".
 */
export function describeCameras(edge, labelOf) {
  const from = labelOf(edge.from_camera_id);
  const to = labelOf(edge.to_camera_id);
  const twoWay = edge.edge_type === 'overlap' || edge.bidirectional;
  return `${from} ${twoWay ? '↔' : '→'} ${to}`;
}

/** Where to draw n cameras in a 0..1 box: side by side for one or two, otherwise round a circle
 * starting at the top. Stable for a given n, so adding a link never moves a camera.
 */
export function circularLayout(count) {
  if (count === 0) return [];
  if (count === 1) return [{ x: 0.5, y: 0.5 }];
  if (count === 2) {
    return [
      { x: 0.25, y: 0.5 },
      { x: 0.75, y: 0.5 },
    ];
  }
  return Array.from({ length: count }, (_, i) => {
    const angle = -Math.PI / 2 + (i / count) * 2 * Math.PI;
    return { x: 0.5 + 0.36 * Math.cos(angle), y: 0.5 + 0.36 * Math.sin(angle) };
  });
}

/** When two cameras have more than one link (an overlap and a transit, say), each gets its own
 * lane so the lines and their labels don't sit on top of each other: a map of edge id -> lane,
 * centred on 0 (… -1, 0, 1 …) and ordered as the links were given.
 */
export function laneOffsets(edges) {
  const groups = new Map();
  edges.forEach((edge) => {
    const key = [edge.from_camera_id, edge.to_camera_id].sort().join('|');
    groups.set(key, [...(groups.get(key) ?? []), edge.id]);
  });
  const lanes = new Map();
  groups.forEach((ids) => {
    ids.forEach((id, index) => lanes.set(id, index - (ids.length - 1) / 2));
  });
  return lanes;
}

/** One sentence for a screen reader: the diagram is drawn, the table beside it is the text. */
export function describeGraph(edges, labelOf) {
  if (edges.length === 0) return 'Camera links diagram: no links yet.';
  const parts = edges.map((edge) => {
    const kind = edge.edge_type === 'overlap' ? 'overlap' : 'transit';
    return `${describeCameras(edge, labelOf)}, ${kind} ${describeTiming(edge)}`;
  });
  return `Camera links diagram: ${parts.join('; ')}.`;
}
