/** The box an operator drags over a frame to say "find things that look like this" (P4-J1).
 * Everything here is arithmetic on fractions of the frame, so what the browser drew at any size
 * is what the api and the retrieval service cut out. Keep MIN_SIDE equal to the contract's
 * (`MIN_CROP_SIDE` in libs/vms_common/.../contracts/search.py).
 */

export const MIN_SIDE = 0.02;

const clamp01 = (v) => Math.min(1, Math.max(0, v));

/** The box between two points, as fractions of a frame drawn `width` × `height` pixels, in
 * whichever direction it was dragged and kept inside the frame. Null for a box too small to mean
 * anything (a click, a slip of the hand).
 *
 * @param {{x: number, y: number}} from  pixels from the frame's top-left corner
 * @param {{x: number, y: number}} to
 * @param {{width: number, height: number}} size  the frame as drawn
 * @returns {{x0: number, y0: number, x1: number, y1: number} | null}
 */
export function boxFromDrag(from, to, size) {
  if (!(size.width > 0) || !(size.height > 0)) return null;
  const ax = clamp01(from.x / size.width);
  const bx = clamp01(to.x / size.width);
  const ay = clamp01(from.y / size.height);
  const by = clamp01(to.y / size.height);
  const box = {
    x0: Math.min(ax, bx),
    y0: Math.min(ay, by),
    x1: Math.max(ax, bx),
    y1: Math.max(ay, by),
  };
  if (box.x1 - box.x0 < MIN_SIDE || box.y1 - box.y0 < MIN_SIDE) return null;
  return box;
}

/** `[x0, y0, x1, y1]`, as the api takes it. */
export function toBbox(box) {
  return [box.x0, box.y0, box.x1, box.y1];
}

/** Where to draw the box over the frame (percentages, so it follows the frame's size). */
export function boxStyle(box) {
  return {
    left: `${box.x0 * 100}%`,
    top: `${box.y0 * 100}%`,
    width: `${(box.x1 - box.x0) * 100}%`,
    height: `${(box.y1 - box.y0) * 100}%`,
  };
}
