import '@testing-library/jest-dom/vitest';

// jsdom has no PointerEvent. Without it `fireEvent.pointerDown(el, { button, clientX })` builds a
// plain Event that silently drops both, so a drag test would pass or fail for the wrong reason.
if (typeof window.PointerEvent === 'undefined') {
  class PointerEvent extends MouseEvent {
    constructor(type, init = {}) {
      super(type, init);
      this.pointerId = init.pointerId ?? 0;
      this.pointerType = init.pointerType ?? 'mouse';
    }
  }
  window.PointerEvent = PointerEvent;
}
