import { z } from 'zod';

export const maskResponseSchema = z.object({
  width: z.number(),
  height: z.number(),
  masks: z.array(
    z.object({
      track_id: z.string().nullable(),
      category: z.string().nullable(),
      bbox: z.array(z.number()),
      rle: z.object({ counts: z.array(z.number()), size: z.tuple([z.number(), z.number()]) }),
    }),
  ),
});

/** Run lengths (row-major, alternating background / object, starting with background) →
 * a Uint8Array of 0/1, one per pixel. Mirrors `rle_encode` in services/retrieval. */
export function rleDecode({ counts, size }) {
  const [h, w] = size;
  const out = new Uint8Array(h * w);
  let pos = 0;
  let value = 0;
  for (const run of counts) {
    if (value) out.fill(1, pos, pos + run);
    pos += run;
    value ^= 1;
  }
  return out;
}
