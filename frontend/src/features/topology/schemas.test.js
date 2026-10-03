import { describe, expect, it } from 'vitest';
import overlap from './fixtures/edge_overlap.json';
import transit from './fixtures/edge_transit.json';
import page from './fixtures/edges_page.json';
import { edgeSchema, edgesPageSchema } from './schemas';

describe('camera link schemas against what the api sends', () => {
  it('accepts an overlap link', () => {
    expect(edgeSchema.parse(overlap)).toMatchObject({
      edge_type: 'overlap',
      tolerance_s: 5,
      min_s: null,
      max_s: null,
      bidirectional: true,
    });
  });

  it('accepts a one-way transit link', () => {
    expect(edgeSchema.parse(transit)).toMatchObject({
      edge_type: 'transit',
      min_s: 10,
      max_s: 45,
      tolerance_s: null,
      bidirectional: false,
    });
  });

  it('accepts a page, including a fractional timing', () => {
    const items = edgesPageSchema.parse(page).items;
    expect(items).toHaveLength(3);
    expect(items[2].min_s).toBe(20.5);
  });

  it.each([
    ['an unknown type', { ...overlap, edge_type: 'teleport' }],
    ['a timing that is not a number', { ...transit, min_s: '10' }],
    ['a missing direction', { ...transit, bidirectional: undefined }],
    ['a creation time with no timezone', { ...overlap, created_at: '2026-10-05T09:00:00' }],
  ])('rejects %s', (_label, bad) => {
    expect(edgeSchema.safeParse(bad).success).toBe(false);
  });
});
