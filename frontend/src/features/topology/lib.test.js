import { describe, expect, it } from 'vitest';
import overlap from './fixtures/edge_overlap.json';
import page from './fixtures/edges_page.json';
import transit from './fixtures/edge_transit.json';
import {
  canSaveLink,
  circularLayout,
  describeCameras,
  describeGraph,
  describeTiming,
  draftFromEdge,
  draftToCreatePayload,
  draftToUpdatePayload,
  laneOffsets,
  linkProblems,
  newLinkDraft,
  parseSeconds,
} from './lib';
import { MAX_TOLERANCE_S, MAX_TRANSIT_S } from './schemas';

const CODES = {
  '01929e6c-0002-7000-8000-000000000001': 'cam01',
  '01929e6c-0002-7000-8000-000000000002': 'cam02',
  '01929e6c-0002-7000-8000-000000000003': 'cam03',
};
const labelOf = (id) => CODES[id] ?? 'unknown camera';

const overlapDraft = (over = {}) => ({ ...newLinkDraft(), from: 'a', to: 'b', ...over });
const transitDraft = (over = {}) => ({
  ...newLinkDraft(),
  from: 'a',
  to: 'b',
  type: 'transit',
  min: '10',
  max: '45',
  ...over,
});

describe('parseSeconds', () => {
  it('reads what was typed', () => {
    expect(parseSeconds('5')).toBe(5);
    expect(parseSeconds(' 12.5 ')).toBe(12.5);
    expect(parseSeconds('0')).toBe(0);
  });

  it.each(['', '   ', 'abc', '1,5', 'Infinity', 'NaN', null, undefined, 5])(
    'gives nothing for %j',
    (value) => {
      expect(parseSeconds(value)).toBeNull();
    },
  );
});

describe('newLinkDraft and draftFromEdge', () => {
  it('starts as an overlap with the api’s default tolerance', () => {
    expect(newLinkDraft()).toEqual({
      from: '',
      to: '',
      type: 'overlap',
      tolerance: '5',
      min: '',
      max: '',
      both: false,
    });
  });

  it('holds an edge’s numbers as text, and blanks for what its type does not have', () => {
    expect(draftFromEdge(transit)).toEqual({
      from: transit.from_camera_id,
      to: transit.to_camera_id,
      type: 'transit',
      tolerance: '5',
      min: '10',
      max: '45',
      both: false,
    });
    expect(draftFromEdge(overlap)).toMatchObject({
      type: 'overlap',
      tolerance: '5',
      min: '',
      max: '',
      both: true,
    });
  });
});

describe('linkProblems', () => {
  it('passes a good overlap and a good transit', () => {
    expect(linkProblems(overlapDraft())).toEqual({});
    expect(linkProblems(transitDraft())).toEqual({});
  });

  it('wants both cameras, and two different ones', () => {
    expect(linkProblems(overlapDraft({ from: '' })).from).toBe('Choose the first camera.');
    expect(linkProblems(overlapDraft({ to: '' })).to).toBe('Choose the second camera.');
    expect(linkProblems(overlapDraft({ from: 'a', to: 'a' })).to).toBe(
      'Choose two different cameras.',
    );
  });

  it('does not check the cameras when editing, because they cannot change', () => {
    expect(linkProblems(overlapDraft({ from: '', to: '' }), { editing: true })).toEqual({});
  });

  it('holds an overlap tolerance to 0..600 s, inclusive', () => {
    expect(linkProblems(overlapDraft({ tolerance: '0' }))).toEqual({});
    expect(linkProblems(overlapDraft({ tolerance: String(MAX_TOLERANCE_S) }))).toEqual({});
    expect(linkProblems(overlapDraft({ tolerance: String(MAX_TOLERANCE_S + 1) })).tolerance).toBe(
      'The time tolerance must be between 0 and 600 seconds.',
    );
    expect(linkProblems(overlapDraft({ tolerance: '-1' })).tolerance).toMatch(/between 0 and 600/);
    expect(linkProblems(overlapDraft({ tolerance: '' })).tolerance).toBe(
      'Enter the time tolerance in seconds.',
    );
    expect(linkProblems(overlapDraft({ tolerance: 'soon' })).tolerance).toMatch(
      /Enter the time tolerance/,
    );
  });

  it('ignores the transit fields on an overlap, and the tolerance on a transit', () => {
    expect(linkProblems(overlapDraft({ min: 'junk', max: '-3' }))).toEqual({});
    expect(linkProblems(transitDraft({ tolerance: 'junk' }))).toEqual({});
  });

  it('holds transit times to 0..3600 s, inclusive, for each end', () => {
    expect(linkProblems(transitDraft({ min: '0', max: String(MAX_TRANSIT_S) }))).toEqual({});
    expect(linkProblems(transitDraft({ max: String(MAX_TRANSIT_S + 1) })).max).toBe(
      'The longest trip must be between 0 and 3600 seconds.',
    );
    expect(linkProblems(transitDraft({ min: '-1' })).min).toBe(
      'The shortest trip must be between 0 and 3600 seconds.',
    );
    expect(linkProblems(transitDraft({ min: '' })).min).toBe('Enter the shortest trip in seconds.');
    expect(linkProblems(transitDraft({ max: '' })).max).toBe('Enter the longest trip in seconds.');
  });

  it('wants the longest trip to be no shorter than the shortest', () => {
    expect(linkProblems(transitDraft({ min: '30', max: '30' }))).toEqual({});
    expect(linkProblems(transitDraft({ min: '30', max: '29' })).max).toBe(
      'The longest trip can’t be shorter than the shortest.',
    );
  });

  it('compares the trip times as numbers, not as text', () => {
    expect(linkProblems(transitDraft({ min: '9', max: '10' }))).toEqual({}); // "10" < "9" as text
    expect(linkProblems(transitDraft({ min: '100', max: '20' })).max).toMatch(/shorter than/);
  });

  it('says the range problem only when both ends are valid', () => {
    const problems = linkProblems(transitDraft({ min: '', max: '5' }));
    expect(problems.min).toBeDefined();
    expect(problems.max).toBeUndefined();
  });

  it('canSaveLink is true exactly when there are no problems', () => {
    expect(canSaveLink(overlapDraft())).toBe(true);
    expect(canSaveLink(overlapDraft({ tolerance: '' }))).toBe(false);
    expect(canSaveLink(overlapDraft({ from: '' }), { editing: true })).toBe(true);
  });
});

describe('payloads', () => {
  it('creates an overlap with its tolerance and no direction', () => {
    expect(draftToCreatePayload(overlapDraft({ tolerance: '7.5', both: true }))).toEqual({
      from_camera_id: 'a',
      to_camera_id: 'b',
      edge_type: 'overlap',
      tolerance_s: 7.5,
    });
  });

  it('creates a transit with its times and direction, and no tolerance', () => {
    expect(draftToCreatePayload(transitDraft({ min: '10', max: '45.5', both: true }))).toEqual({
      from_camera_id: 'a',
      to_camera_id: 'b',
      edge_type: 'transit',
      min_s: 10,
      max_s: 45.5,
      bidirectional: true,
    });
    expect(draftToCreatePayload(transitDraft()).bidirectional).toBe(false);
  });

  it('updates only what the edge’s type has — never its cameras or type', () => {
    expect(draftToUpdatePayload(overlapDraft({ tolerance: '9' }))).toEqual({ tolerance_s: 9 });
    expect(draftToUpdatePayload(transitDraft({ both: true }))).toEqual({
      min_s: 10,
      max_s: 45,
      bidirectional: true,
    });
  });

  it('round-trips an edge through the form', () => {
    expect(draftToUpdatePayload(draftFromEdge(transit))).toEqual({
      min_s: 10,
      max_s: 45,
      bidirectional: false,
    });
    expect(draftToUpdatePayload(draftFromEdge(overlap))).toEqual({ tolerance_s: 5 });
  });
});

describe('describeTiming and describeCameras', () => {
  const [overlapEdge, oneWay, twoWay] = page.items;

  it('shows an overlap as ± its tolerance and a transit as its range', () => {
    expect(describeTiming(overlapEdge)).toBe('±5 s');
    expect(describeTiming(oneWay)).toBe('10–45 s');
    expect(describeTiming(twoWay)).toBe('20.5–90 s');
  });

  it('trims float noise', () => {
    expect(describeTiming({ ...overlapEdge, tolerance_s: 0.1 + 0.2 })).toBe('±0.3 s');
  });

  it('uses an arrow for one way and a double arrow for both', () => {
    expect(describeCameras(overlapEdge, labelOf)).toBe('cam01 ↔ cam02'); // an overlap is always two-way
    expect(describeCameras(oneWay, labelOf)).toBe('cam02 → cam03');
    expect(describeCameras(twoWay, labelOf)).toBe('cam01 ↔ cam03');
  });

  it('treats an overlap as two-way whatever its direction flag says', () => {
    expect(describeCameras({ ...overlapEdge, bidirectional: false }, labelOf)).toBe(
      'cam01 ↔ cam02',
    );
  });

  it('names a camera that is no longer configured', () => {
    expect(describeCameras({ ...oneWay, to_camera_id: 'gone' }, labelOf)).toBe(
      'cam02 → unknown camera',
    );
  });
});

describe('circularLayout', () => {
  it('has nothing for no cameras, the middle for one, side by side for two', () => {
    expect(circularLayout(0)).toEqual([]);
    expect(circularLayout(1)).toEqual([{ x: 0.5, y: 0.5 }]);
    expect(circularLayout(2)).toEqual([
      { x: 0.25, y: 0.5 },
      { x: 0.75, y: 0.5 },
    ]);
  });

  it('puts three or more round a circle, the first at the top, clockwise', () => {
    const layout = circularLayout(4);
    expect(layout).toHaveLength(4);
    expect(layout[0].x).toBeCloseTo(0.5);
    expect(layout[0].y).toBeLessThan(0.5); // the top
    expect(layout[1].x).toBeGreaterThan(0.5); // then the right
    expect(layout[2].y).toBeGreaterThan(0.5); // the bottom
    expect(layout[3].x).toBeLessThan(0.5); // the left
  });

  it('keeps every camera inside the box and a fixed distance from the middle', () => {
    for (const n of [3, 5, 8, 12]) {
      for (const { x, y } of circularLayout(n)) {
        expect(x).toBeGreaterThan(0);
        expect(x).toBeLessThan(1);
        expect(y).toBeGreaterThan(0);
        expect(y).toBeLessThan(1);
        expect(Math.hypot(x - 0.5, y - 0.5)).toBeCloseTo(0.36);
      }
    }
  });

  it('does not move cameras when the count is the same', () => {
    expect(circularLayout(6)).toEqual(circularLayout(6));
  });
});

describe('laneOffsets', () => {
  const edge = (id, from, to) => ({ id, from_camera_id: from, to_camera_id: to });

  it('gives a lone link the middle lane', () => {
    expect(laneOffsets([edge('e1', 'a', 'b')]).get('e1')).toBe(0);
  });

  it('spreads links between the same two cameras either side of the middle', () => {
    const lanes = laneOffsets([edge('e1', 'a', 'b'), edge('e2', 'a', 'b')]);
    expect([lanes.get('e1'), lanes.get('e2')]).toEqual([-0.5, 0.5]);
    const three = laneOffsets([edge('e1', 'a', 'b'), edge('e2', 'a', 'b'), edge('e3', 'a', 'b')]);
    expect([three.get('e1'), three.get('e2'), three.get('e3')]).toEqual([-1, 0, 1]);
  });

  it('treats a→b and b→a as the same pair', () => {
    const lanes = laneOffsets([edge('e1', 'a', 'b'), edge('e2', 'b', 'a')]);
    expect(lanes.get('e1')).not.toBe(lanes.get('e2'));
  });

  it('does not spread links between different pairs', () => {
    const lanes = laneOffsets([edge('e1', 'a', 'b'), edge('e2', 'a', 'c')]);
    expect([lanes.get('e1'), lanes.get('e2')]).toEqual([0, 0]);
  });
});

describe('describeGraph', () => {
  it('says there are no links', () => {
    expect(describeGraph([], labelOf)).toBe('Camera links diagram: no links yet.');
  });

  it('reads every link out', () => {
    expect(describeGraph(page.items.slice(0, 2), labelOf)).toBe(
      'Camera links diagram: cam01 ↔ cam02, overlap ±5 s; cam02 → cam03, transit 10–45 s.',
    );
  });
});
