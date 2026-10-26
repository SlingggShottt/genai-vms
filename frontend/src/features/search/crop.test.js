import { describe, expect, it } from 'vitest';
import { MIN_SIDE, boxFromDrag, boxStyle, toBbox } from './crop';

const SIZE = { width: 400, height: 200 };

describe('boxFromDrag', () => {
  it('turns pixels into fractions of the frame', () => {
    expect(boxFromDrag({ x: 100, y: 50 }, { x: 300, y: 150 }, SIZE)).toEqual({
      x0: 0.25,
      y0: 0.25,
      x1: 0.75,
      y1: 0.75,
    });
  });

  it('is the same box whichever way it was dragged', () => {
    const a = boxFromDrag({ x: 100, y: 50 }, { x: 300, y: 150 }, SIZE);
    expect(boxFromDrag({ x: 300, y: 150 }, { x: 100, y: 50 }, SIZE)).toEqual(a);
    expect(boxFromDrag({ x: 300, y: 50 }, { x: 100, y: 150 }, SIZE)).toEqual(a);
  });

  it('keeps a drag that left the frame inside it', () => {
    expect(boxFromDrag({ x: -50, y: -10 }, { x: 900, y: 80 }, SIZE)).toEqual({
      x0: 0,
      y0: 0,
      x1: 1,
      y1: 0.4,
    });
  });

  it('gives no box for a click or a sliver, because the api would refuse it', () => {
    expect(boxFromDrag({ x: 100, y: 100 }, { x: 100, y: 100 }, SIZE)).toBeNull();
    expect(
      boxFromDrag({ x: 100, y: 100 }, { x: 300, y: 100 + 200 * MIN_SIDE * 0.5 }, SIZE),
    ).toBeNull();
    expect(
      boxFromDrag({ x: 100, y: 100 }, { x: 100 + 400 * MIN_SIDE * 0.5, y: 190 }, SIZE),
    ).toBeNull();
  });

  it('gives a box exactly one minimum side wide', () => {
    expect(
      boxFromDrag({ x: 0, y: 0 }, { x: 400 * MIN_SIDE, y: 200 * MIN_SIDE }, SIZE),
    ).not.toBeNull();
  });

  it('gives no box for a frame with no size (not drawn yet)', () => {
    expect(boxFromDrag({ x: 1, y: 1 }, { x: 5, y: 5 }, { width: 0, height: 0 })).toBeNull();
  });
});

describe('toBbox and boxStyle', () => {
  const box = { x0: 0.25, y0: 0.1, x1: 0.75, y1: 0.6 };

  it('is the order the api takes', () => {
    expect(toBbox(box)).toEqual([0.25, 0.1, 0.75, 0.6]);
  });

  it('is drawn as percentages of the frame', () => {
    expect(boxStyle(box)).toEqual({ left: '25%', top: '10%', width: '50%', height: '50%' });
  });
});
