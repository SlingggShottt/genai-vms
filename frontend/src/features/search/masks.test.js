import { describe, expect, it } from 'vitest';
import { rleDecode } from './masks';

describe('rleDecode', () => {
  it('expands alternating background/object runs row-major', () => {
    // 2×3: [0 0 1 / 1 1 0]  -> runs 2 zeros, 3 ones, 1 zero
    expect(Array.from(rleDecode({ counts: [2, 3, 1], size: [2, 3] }))).toEqual([0, 0, 1, 1, 1, 0]);
  });

  it('starts with object pixels when the first run of background is empty', () => {
    expect(Array.from(rleDecode({ counts: [0, 2, 2], size: [2, 2] }))).toEqual([1, 1, 0, 0]);
  });
});
