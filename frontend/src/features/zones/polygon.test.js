import { describe, expect, it } from 'vitest';
import {
  EDGE_SNAP,
  MAX_POINTS,
  MIN_AREA,
  MIN_POINTS,
  addPoint,
  centroid,
  clamp01,
  crossesItself,
  insertIndexFor,
  movePoint,
  nudge,
  polygonArea,
  polygonProblems,
  removePoint,
  segmentsIntersect,
  suggestedInsertion,
  toNormalized,
} from './polygon';

const SQUARE = [
  [0.2, 0.2],
  [0.8, 0.2],
  [0.8, 0.8],
  [0.2, 0.8],
];
const TRIANGLE_UNIT = [
  [0.2, 0.2],
  [0.8, 0.2],
  [0.5, 0.8],
];
const BOWTIE = [
  [0.2, 0.2],
  [0.8, 0.8],
  [0.8, 0.2],
  [0.2, 0.8],
];

describe('toNormalized', () => {
  const rect = { left: 100, top: 50, width: 400, height: 200 };

  it('maps a pointer inside the frame to 0..1', () => {
    expect(toNormalized(300, 150, rect)).toEqual([0.5, 0.5]);
    expect(toNormalized(100, 50, rect)).toEqual([0, 0]);
    expect(toNormalized(500, 250, rect)).toEqual([1, 1]);
  });

  it('clamps a pointer outside the frame to its edge', () => {
    expect(toNormalized(0, 0, rect)).toEqual([0, 0]);
    expect(toNormalized(9999, 9999, rect)).toEqual([1, 1]);
  });

  it('rounds to four decimals so the payload stays tidy', () => {
    expect(toNormalized(100 + 400 / 3, 50 + 200 / 3, rect)).toEqual([0.3333, 0.3333]);
  });

  it('gives nothing for a frame that has no size yet', () => {
    expect(toNormalized(10, 10, { left: 0, top: 0, width: 0, height: 100 })).toBeNull();
    expect(toNormalized(10, 10, { left: 0, top: 0, width: 100, height: 0 })).toBeNull();
    expect(toNormalized(10, 10, null)).toBeNull();
  });
});

describe('clamp01 and nudge', () => {
  it('clamps', () => {
    expect(clamp01(-0.1)).toBe(0);
    expect(clamp01(1.1)).toBe(1);
    expect(clamp01(0.4)).toBe(0.4);
  });

  it('moves a point and keeps it inside the frame', () => {
    expect(nudge([0.5, 0.5], 0.01, -0.01)).toEqual([0.51, 0.49]);
    expect(nudge([0.995, 0.005], 0.05, -0.05)).toEqual([1, 0]);
    expect(nudge([0.1, 0.1], 0.1 + 0.2 - 0.3, 0)[0]).toBe(0.1); // float noise is rounded away
  });
});

describe('insertIndexFor', () => {
  it('appends while the outline has fewer than three points', () => {
    expect(insertIndexFor([], [0.5, 0.5])).toBe(0);
    expect(
      insertIndexFor(
        [
          [0.1, 0.1],
          [0.9, 0.1],
        ],
        [0.5, 0.1],
      ),
    ).toBe(2);
  });

  it('inserts into the edge a click lands on', () => {
    expect(insertIndexFor(SQUARE, [0.5, 0.2])).toBe(1); // top edge: between points 0 and 1
    expect(insertIndexFor(SQUARE, [0.8, 0.5])).toBe(2); // right edge
    expect(insertIndexFor(SQUARE, [0.5, 0.8])).toBe(3); // bottom edge
  });

  it('puts a point on the closing edge (last point back to first) at the end', () => {
    expect(insertIndexFor(SQUARE, [0.2, 0.5])).toBe(4);
  });

  it('appends when the click is clear of every edge', () => {
    expect(insertIndexFor(SQUARE, [0.5, 0.5])).toBe(4);
    expect(insertIndexFor(SQUARE, [0.1, 0.9])).toBe(4);
  });

  it('snaps within EDGE_SNAP and not beyond it', () => {
    const justInside = 0.2 + EDGE_SNAP * 0.9;
    const justOutside = 0.2 + EDGE_SNAP * 1.2;
    expect(insertIndexFor(SQUARE, [0.5, justInside], 1)).toBe(1);
    expect(insertIndexFor(SQUARE, [0.5, justOutside], 1)).toBe(4);
  });

  it('measures vertical gaps in width units, so a wide frame is not more forgiving up and down', () => {
    // 0.05 of the frame's height below the top edge is 0.025 widths on a 2:1 frame (inside
    // EDGE_SNAP) but 0.05 widths on a square one (outside it).
    const offset = 0.2 + 0.05;
    expect(insertIndexFor(SQUARE, [0.5, offset], 2)).toBe(1); // 0.025 widths: snaps
    expect(insertIndexFor(SQUARE, [0.5, offset], 1)).toBe(4); // 0.05 widths: appends
  });

  it('picks the nearest edge when two are close', () => {
    const narrow = [
      [0.1, 0.1],
      [0.9, 0.1],
      [0.9, 0.12],
      [0.1, 0.12],
    ];
    expect(insertIndexFor(narrow, [0.5, 0.105], 1)).toBe(1); // nearer the top edge
    expect(insertIndexFor(narrow, [0.5, 0.115], 1)).toBe(3); // nearer the bottom edge
  });
});

describe('suggestedInsertion', () => {
  it('builds a starter triangle in the middle of the frame, one corner at a time', () => {
    const first = suggestedInsertion([]);
    expect(first).toEqual({ index: 0, point: [0.35, 0.65] });
    const second = suggestedInsertion([first.point]);
    expect(second).toEqual({ index: 1, point: [0.65, 0.65] });
    const third = suggestedInsertion([first.point, second.point]);
    expect(third).toEqual({ index: 2, point: [0.5, 0.35] });
    expect(polygonProblems([first.point, second.point, third.point])).toEqual([]);
  });

  it('then splits the longest edge at its middle', () => {
    const wide = [
      [0.1, 0.1],
      [0.9, 0.1], // 0.8 long: the longest
      [0.9, 0.3],
      [0.1, 0.3],
    ];
    expect(suggestedInsertion(wide, 1)).toEqual({ index: 1, point: [0.5, 0.1] });
  });

  it('can split the closing edge, putting the point at the end', () => {
    const tall = [
      [0.1, 0.1],
      [0.3, 0.1],
      [0.3, 0.9],
      [0.1, 0.9],
    ];
    // Edges 1 (0.3,0.1 -> 0.3,0.9) and 3 (0.1,0.9 -> 0.1,0.1) tie at 0.8; the first wins.
    expect(suggestedInsertion(tall, 1)).toEqual({ index: 2, point: [0.3, 0.5] });
    // Here the longest edge is the one from the last point back to the first.
    const closing = [
      [0.9, 0.1],
      [0.9, 0.2],
      [0.8, 0.2],
      [0.1, 0.9],
    ];
    expect(suggestedInsertion(closing, 1)).toEqual({ index: 4, point: [0.5, 0.5] });
  });

  it('weighs a vertical edge by the frame aspect, so it is not shortchanged on a wide frame', () => {
    const shape = [
      [0.1, 0.1],
      [0.5, 0.1], // 0.4 across
      [0.5, 0.7], // 0.6 down = 0.6 / 2 = 0.3 widths on a 2:1 frame (shorter than 0.4)
      [0.1, 0.7],
    ];
    expect(suggestedInsertion(shape, 2).index).toBe(1);
    expect(suggestedInsertion(shape, 1).index).toBe(2); // on a square frame 0.6 is the longest
  });
});

describe('addPoint, movePoint, removePoint', () => {
  it('adds in place and does not mutate its input', () => {
    const before = SQUARE.map((p) => [...p]);
    const after = addPoint(SQUARE, [0.5, 0.2]);
    expect(after).toHaveLength(5);
    expect(after[1]).toEqual([0.5, 0.2]);
    expect(SQUARE).toEqual(before);
  });

  it('refuses a point beyond the maximum', () => {
    const full = Array.from({ length: MAX_POINTS }, (_, i) => [i / 100, 0.5]);
    expect(addPoint(full, [0.9, 0.9])).toBe(full);
  });

  it('allows exactly the maximum', () => {
    const almost = Array.from({ length: MAX_POINTS - 1 }, (_, i) => [i / 100, 0.5]);
    expect(addPoint(almost, [0.9, 0.9])).toHaveLength(MAX_POINTS);
  });

  it('moves one point only', () => {
    const moved = movePoint(SQUARE, 2, [0.9, 0.9]);
    expect(moved[2]).toEqual([0.9, 0.9]);
    expect(moved.filter((p, i) => i !== 2)).toEqual(SQUARE.filter((p, i) => i !== 2));
    expect(SQUARE[2]).toEqual([0.8, 0.8]);
  });

  it('removes one point only', () => {
    expect(removePoint(SQUARE, 1)).toEqual([SQUARE[0], SQUARE[2], SQUARE[3]]);
    expect(SQUARE).toHaveLength(4);
  });
});

describe('polygonArea', () => {
  it('measures a square and is orientation-independent', () => {
    expect(polygonArea(SQUARE)).toBeCloseTo(0.36);
    expect(polygonArea([...SQUARE].reverse())).toBeCloseTo(0.36);
  });

  it('measures a triangle', () => {
    expect(
      polygonArea([
        [0, 0],
        [1, 0],
        [0, 1],
      ]),
    ).toBeCloseTo(0.5);
  });

  it('is zero for points in a line', () => {
    expect(
      polygonArea([
        [0.1, 0.1],
        [0.5, 0.5],
        [0.9, 0.9],
      ]),
    ).toBeCloseTo(0);
  });
});

describe('segmentsIntersect', () => {
  it('detects a proper crossing', () => {
    expect(segmentsIntersect([0, 0], [1, 1], [0, 1], [1, 0])).toBe(true);
  });

  it('is false for separate segments', () => {
    expect(segmentsIntersect([0, 0], [1, 0], [0, 1], [1, 1])).toBe(false);
    expect(segmentsIntersect([0, 0], [0.4, 0.4], [0.6, 0.6], [1, 1])).toBe(false); // collinear gap
  });

  it('counts touching at an end and overlapping as meeting', () => {
    expect(segmentsIntersect([0, 0], [1, 1], [1, 1], [2, 0])).toBe(true); // end touches end
    expect(segmentsIntersect([0, 0], [1, 0], [0.5, 0], [0.5, 1])).toBe(true); // end on the middle
    expect(segmentsIntersect([0, 0], [1, 0], [0.5, 0], [2, 0])).toBe(true); // collinear overlap
  });
});

describe('crossesItself', () => {
  it('is false for a convex outline and for a concave one', () => {
    expect(crossesItself(SQUARE)).toBe(false);
    expect(
      crossesItself([
        [0.1, 0.1],
        [0.9, 0.1],
        [0.5, 0.5],
        [0.9, 0.9],
        [0.1, 0.9],
      ]),
    ).toBe(false);
  });

  it('is true for a bow-tie', () => {
    expect(crossesItself(BOWTIE)).toBe(true);
  });

  it('is true when the closing edge cuts an earlier edge', () => {
    expect(
      crossesItself([
        [0.2, 0.2],
        [0.8, 0.2],
        [0.8, 0.8],
        [0.5, 0.1],
        [0.2, 0.5],
      ]),
    ).toBe(true);
  });

  it('is true when a corner touches a distant edge', () => {
    expect(
      crossesItself([
        [0.1, 0.1],
        [0.9, 0.1],
        [0.9, 0.9],
        [0.5, 0.1], // sits on the top edge
        [0.1, 0.9],
      ]),
    ).toBe(true);
  });

  it('never calls a triangle self-crossing', () => {
    expect(
      crossesItself([
        [0.1, 0.1],
        [0.9, 0.1],
        [0.5, 0.9],
      ]),
    ).toBe(false);
  });

  it('does not mistake neighbours, including first and last, for a crossing', () => {
    // Every pair of neighbouring edges meets at a corner; only non-neighbours may be flagged.
    expect(crossesItself(SQUARE)).toBe(false);
    expect(crossesItself([...SQUARE].reverse())).toBe(false);
  });
});

describe('polygonProblems', () => {
  it('asks for more points below the minimum, and nothing else', () => {
    expect(polygonProblems([])).toEqual(['Add at least 3 points to outline the zone.']);
    expect(
      polygonProblems([
        [0.1, 0.1],
        [0.9, 0.9],
      ]),
    ).toHaveLength(1);
  });

  it('is empty for a fine outline, from the minimum number of points up to the maximum', () => {
    expect(polygonProblems(SQUARE)).toEqual([]);
    expect(
      polygonProblems([
        [0.1, 0.1],
        [0.9, 0.1],
        [0.5, 0.9],
      ]),
    ).toEqual([]);
    const ring = Array.from({ length: MAX_POINTS }, (_, i) => {
      const angle = (i / MAX_POINTS) * 2 * Math.PI;
      return [0.5 + 0.4 * Math.cos(angle), 0.5 + 0.4 * Math.sin(angle)];
    });
    expect(polygonProblems(ring)).toEqual([]);
  });

  it('refuses more than the maximum', () => {
    const ring = Array.from({ length: MAX_POINTS + 1 }, (_, i) => {
      const angle = (i / (MAX_POINTS + 1)) * 2 * Math.PI;
      return [0.5 + 0.4 * Math.cos(angle), 0.5 + 0.4 * Math.sin(angle)];
    });
    expect(polygonProblems(ring)).toEqual([
      `Use at most ${MAX_POINTS} points. Remove some to simplify the outline.`,
    ]);
  });

  it('says how to fix a crossing outline', () => {
    expect(polygonProblems(BOWTIE)).toEqual([
      "The outline crosses itself. Move a point so the edges don't cross.",
    ]);
  });

  it('flags a sliver, and a straight line of points', () => {
    const sliver = [
      [0.1, 0.1],
      [0.9, 0.1],
      [0.9, 0.1 + (MIN_AREA / 0.8) * 0.5],
      [0.1, 0.1 + (MIN_AREA / 0.8) * 0.5],
    ];
    expect(polygonProblems(sliver)[0]).toMatch(/too small/);
    expect(
      polygonProblems([
        [0.1, 0.1],
        [0.5, 0.5],
        [0.9, 0.9],
      ])[0],
    ).toMatch(/too small/);
  });

  it('accepts an area just above the minimum', () => {
    const height = (MIN_AREA / 0.8) * 1.5;
    expect(
      polygonProblems([
        [0.1, 0.1],
        [0.9, 0.1],
        [0.9, 0.1 + height],
        [0.1, 0.1 + height],
      ]),
    ).toEqual([]);
  });

  it('reports a crossing outline once, whatever its size', () => {
    // Its lobes cancel in the area sum, so a large bow-tie must not also be called "too small".
    const tinyKnot = [
      [0.1, 0.1],
      [0.1001, 0.1001],
      [0.1001, 0.1],
      [0.1, 0.1001],
    ];
    expect(polygonProblems(tinyKnot)).toHaveLength(1);
    expect(polygonProblems(BOWTIE)).toHaveLength(1);
  });
});

describe('centroid', () => {
  it('is the mean of the corners', () => {
    expect(centroid(SQUARE)).toEqual([0.5, 0.5]);
    const [x, y] = centroid([
      [0, 0],
      [0.3, 0],
      [0, 0.6],
    ]);
    expect(x).toBeCloseTo(0.1);
    expect(y).toBeCloseTo(0.2);
  });
});

describe('the limits', () => {
  it("are the api's (services/api/src/api/domain/zones.py)", () => {
    expect(MIN_POINTS).toBe(3);
    expect(MAX_POINTS).toBe(32);
  });

  it('treat a zone of 0.05 % of the frame as just big enough, and smaller as too small', () => {
    // Right triangles with a leg of 1: area = height / 2, exactly representable.
    const triangle = (height) => [
      [0, 0],
      [1, 0],
      [0, height],
    ];
    expect(polygonProblems(triangle(0.001))).toEqual([]); // area 0.0005, the minimum
    expect(polygonProblems(triangle(0.0004))[0]).toMatch(/too small/); // 0.0002
    expect(polygonProblems(triangle(0.01))).toEqual([]); // 0.005
  });
});

describe('edges of the smallest outline', () => {
  it('can take a new point: a triangle already has edges', () => {
    expect(insertIndexFor(TRIANGLE_UNIT, [0.5, 0.2])).toBe(1);
    expect(insertIndexFor(TRIANGLE_UNIT, [0.65, 0.5], 1)).toBe(2);
  });

  it('is split at the middle of its longest edge by "Add point"', () => {
    // Edges: 0.6, then two of about 0.67 (the first of them wins).
    expect(suggestedInsertion(TRIANGLE_UNIT, 1)).toEqual({ index: 2, point: [0.65, 0.5] });
  });
});

describe('a click near the line an edge lies on, but beyond its end', () => {
  it('does not snap to that edge', () => {
    // On the line of the top edge (y = 0.2), to the right of its end; clear of every real edge.
    expect(insertIndexFor(SQUARE, [0.95, 0.2], 1)).toBe(4);
    // On the line of the right edge (x = 0.8), below its end.
    expect(insertIndexFor(SQUARE, [0.8, 0.95], 1)).toBe(4);
  });
});

describe('segmentsIntersect, each way two segments can meet', () => {
  const across = [
    [0.5, 0],
    [0.5, 1],
  ];
  const flat = [
    [0, 0],
    [1, 0],
  ];

  it('is false when one segment reaches across the other’s line but not the other way', () => {
    // `flat` straddles the vertical line through `above`, yet `above` is wholly above `flat`.
    const above = [
      [0.5, 1],
      [0.5, 2],
    ];
    expect(segmentsIntersect(...flat, ...above)).toBe(false);
    expect(segmentsIntersect(...above, ...flat)).toBe(false);
  });

  it('is true when any one end of either segment lies on the middle of the other', () => {
    expect(segmentsIntersect(...across, ...flat)).toBe(true); // first segment's first end
    expect(segmentsIntersect([0.5, 1], [0.5, 0], ...flat)).toBe(true); // first segment's second end
    expect(segmentsIntersect(...flat, ...across)).toBe(true); // second segment's first end
    expect(segmentsIntersect(...flat, [0.5, 1], [0.5, 0])).toBe(true); // second segment's second end
  });
});
