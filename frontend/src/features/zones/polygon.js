/** Geometry for the zone editor. A point is `[x, y]`, both normalised to 0..1 of the camera
 * frame — the api's contract (services/api/src/api/domain/zones.py). These are pure functions;
 * the editor component only wires pointers and keys to them.
 */
export const MIN_POINTS = 3;
export const MAX_POINTS = 32;
// A click within this distance of an edge (as a fraction of the frame's width) inserts a point
// into that edge instead of appending one, so an outline can be refined without redrawing it.
export const EDGE_SNAP = 0.03;
// Below this a zone is a sliver nobody can see or hit: 0.05 % of the frame.
export const MIN_AREA = 0.0005;

export const clamp01 = (value) => Math.min(1, Math.max(0, value));
const round4 = (value) => Math.round(value * 1e4) / 1e4;

/** Pointer position -> normalised point, clamped to the frame. `null` for an unmeasured frame. */
export function toNormalized(clientX, clientY, rect) {
  if (!rect || rect.width <= 0 || rect.height <= 0) return null;
  return [
    round4(clamp01((clientX - rect.left) / rect.width)),
    round4(clamp01((clientY - rect.top) / rect.height)),
  ];
}

/** `point` moved by (dx, dy) and kept inside the frame. */
export function nudge(point, dx, dy) {
  return [round4(clamp01(point[0] + dx)), round4(clamp01(point[1] + dy))];
}

// Distances are taken in "width units" so a 16:9 frame doesn't make vertical gaps look 1.8x
// shorter than horizontal ones: y is divided by the frame's aspect ratio (width / height).
function distanceToSegment(point, a, b, aspect) {
  const [px, py] = [point[0], point[1] / aspect];
  const [ax, ay] = [a[0], a[1] / aspect];
  const [bx, by] = [b[0], b[1] / aspect];
  const [dx, dy] = [bx - ax, by - ay];
  const lengthSquared = dx * dx + dy * dy;
  const t = lengthSquared === 0 ? 0 : clamp01(((px - ax) * dx + (py - ay) * dy) / lengthSquared);
  return Math.hypot(px - (ax + t * dx), py - (ay + t * dy));
}

/** Where a new point at `point` goes: into the nearest edge when the click landed on one (index
 * of the edge's second point), otherwise at the end. An unfinished outline has no edges to hit.
 */
export function insertIndexFor(points, point, aspect = 16 / 9) {
  if (points.length < MIN_POINTS) return points.length;
  let best = { index: points.length, distance: Infinity };
  points.forEach((start, i) => {
    const end = points[(i + 1) % points.length];
    const distance = distanceToSegment(point, start, end, aspect);
    if (distance < best.distance) best = { index: i + 1, distance };
  });
  return best.distance <= EDGE_SNAP ? best.index : points.length;
}

// The first three points of "Add point" (for someone who can't click the frame) make a triangle
// in the middle of it, which can then be moved into place with the arrow keys.
const STARTER_TRIANGLE = [
  [0.35, 0.65],
  [0.65, 0.65],
  [0.5, 0.35],
];

/** Where "Add point" puts a point: the next corner of a starter triangle, then the middle of the
 * longest edge — somewhere with room around it, never on top of another point.
 */
export function suggestedInsertion(points, aspect = 16 / 9) {
  if (points.length < STARTER_TRIANGLE.length) {
    return { index: points.length, point: STARTER_TRIANGLE[points.length] };
  }
  let longest = { index: 1, length: -1 };
  points.forEach((start, i) => {
    const end = points[(i + 1) % points.length];
    const length = Math.hypot(end[0] - start[0], (end[1] - start[1]) / aspect);
    if (length > longest.length) longest = { index: i + 1, length };
  });
  const start = points[longest.index - 1];
  const end = points[longest.index % points.length];
  return {
    index: longest.index,
    point: [round4((start[0] + end[0]) / 2), round4((start[1] + end[1]) / 2)],
  };
}

/** `points` with `point` added; unchanged once the outline is full. */
export function addPoint(points, point, aspect) {
  if (points.length >= MAX_POINTS) return points;
  const index = insertIndexFor(points, point, aspect);
  return [...points.slice(0, index), point, ...points.slice(index)];
}

export function movePoint(points, index, point) {
  return points.map((existing, i) => (i === index ? point : existing));
}

export function removePoint(points, index) {
  return points.filter((_, i) => i !== index);
}

/** Area by the shoelace formula, in normalised units (the whole frame is 1). */
export function polygonArea(points) {
  let twice = 0;
  points.forEach(([x1, y1], i) => {
    const [x2, y2] = points[(i + 1) % points.length];
    twice += x1 * y2 - x2 * y1;
  });
  return Math.abs(twice) / 2;
}

const cross = (o, a, b) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
const within = (value, a, b) => value >= Math.min(a, b) && value <= Math.max(a, b);
const onSegment = (a, b, c) => within(c[0], a[0], b[0]) && within(c[1], a[1], b[1]);

/** Do segments p1-p2 and p3-p4 share a point (touching and overlapping count)? */
export function segmentsIntersect(p1, p2, p3, p4) {
  const d1 = cross(p3, p4, p1);
  const d2 = cross(p3, p4, p2);
  const d3 = cross(p1, p2, p3);
  const d4 = cross(p1, p2, p4);
  if (((d1 > 0 && d2 < 0) || (d1 < 0 && d2 > 0)) && ((d3 > 0 && d4 < 0) || (d3 < 0 && d4 > 0))) {
    return true;
  }
  return (
    (d1 === 0 && onSegment(p3, p4, p1)) ||
    (d2 === 0 && onSegment(p3, p4, p2)) ||
    (d3 === 0 && onSegment(p1, p2, p3)) ||
    (d4 === 0 && onSegment(p1, p2, p4))
  );
}

/** Does any edge cross or touch an edge it isn't next to? Neighbours share a corner by design. */
export function crossesItself(points) {
  const count = points.length;
  if (count < 4) return false;
  for (let i = 0; i < count; i += 1) {
    for (let j = i + 2; j < count; j += 1) {
      if (i === 0 && j === count - 1) continue; // the closing edge neighbours the first
      if (
        segmentsIntersect(points[i], points[(i + 1) % count], points[j], points[(j + 1) % count])
      ) {
        return true;
      }
    }
  }
  return false;
}

/** What stops this outline from being saved, as messages that say how to fix it. Empty when fine. */
export function polygonProblems(points) {
  if (points.length < MIN_POINTS) {
    return [`Add at least ${MIN_POINTS} points to outline the zone.`];
  }
  if (points.length > MAX_POINTS) {
    return [`Use at most ${MAX_POINTS} points. Remove some to simplify the outline.`];
  }
  // A crossing outline's lobes cancel in the shoelace sum, so its "area" says nothing about its
  // size: report the crossing alone rather than also calling a large bow-tie too small.
  if (crossesItself(points)) {
    return ["The outline crosses itself. Move a point so the edges don't cross."];
  }
  if (polygonArea(points) < MIN_AREA) {
    return ['The zone is too small to see. Spread the points out to enclose more of the frame.'];
  }
  return [];
}

/** Mean of the corners — close enough to centre a label on, and always defined. */
export function centroid(points) {
  const sum = points.reduce((acc, [x, y]) => [acc[0] + x, acc[1] + y], [0, 0]);
  return [sum[0] / points.length, sum[1] / points.length];
}
