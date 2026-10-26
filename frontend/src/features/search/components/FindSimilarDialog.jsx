import { useRef, useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { errorMessage } from '@/lib/errorMessage';
import { runCropSearch } from '../api';
import { boxFromDrag, boxStyle, toBbox } from '../crop';
import { ResultCard } from './ResultCard';

/** "Find similar" (P4-J1, FR-SRC-06): draw a box over part of a frame and see where else
 * something that looks like it appears. The box is sent as fractions of the frame, with the frame
 * named the way this page knows it (an event's keyframe, a search result, a camera and a moment);
 * the server cuts it out of the stored frame, so no storage address is ever in the browser.
 *
 * Dragging is a mouse gesture; "Use the whole frame" does the same job from the keyboard when the
 * picture is already of the thing itself.
 *
 * @param {{frame: {imageUrl: string, label: string, ref: object, cameras?: string[]}|null,
 *   onClose: () => void}} props  `frame` null = closed
 */
export function FindSimilarDialog({ frame, onClose }) {
  const surface = useRef(null);
  const [anchor, setAnchor] = useState(null); // pixels, while the button is held
  const [pointer, setPointer] = useState(null);
  const [box, setBox] = useState(null);
  const [failed, setFailed] = useState(false);
  const search = useMutation({ mutationFn: runCropSearch });

  const sizeOf = () => {
    const rect = surface.current?.getBoundingClientRect();
    return { rect, size: { width: rect?.width ?? 0, height: rect?.height ?? 0 } };
  };
  const at = (event) => {
    const { rect } = sizeOf();
    return { x: event.clientX - (rect?.left ?? 0), y: event.clientY - (rect?.top ?? 0) };
  };

  function down(event) {
    if (event.button !== 0) return;
    event.preventDefault();
    const point = at(event);
    setAnchor(point);
    setPointer(point);
    setBox(null);
    search.reset();
  }
  function move(event) {
    if (anchor) setPointer(at(event));
  }
  function up(event) {
    if (!anchor) return;
    setBox(boxFromDrag(anchor, at(event), sizeOf().size));
    setAnchor(null);
    setPointer(null);
  }
  function close() {
    setAnchor(null);
    setPointer(null);
    setBox(null);
    setFailed(false);
    search.reset();
    onClose();
  }

  const drawing = anchor && pointer ? boxFromDrag(anchor, pointer, sizeOf().size) : null;
  const shown = drawing ?? box;
  const results = search.data?.results ?? [];

  return (
    <Dialog open={Boolean(frame)} onOpenChange={(open) => !open && close()}>
      <DialogContent className="max-h-[92vh] max-w-4xl overflow-auto">
        <DialogHeader>
          <DialogTitle>Find similar</DialogTitle>
          <DialogDescription>
            {frame?.label}. Drag a box around the person or object to look for in other footage.
          </DialogDescription>
        </DialogHeader>

        {frame && (
          // eslint-disable-next-line jsx-a11y/no-static-element-interactions -- drawing is a mouse gesture; "Use the whole frame" below is the keyboard control
          <div
            ref={surface}
            data-testid="crop-surface"
            onMouseDown={down}
            onMouseMove={move}
            onMouseUp={up}
            onMouseLeave={up}
            className="relative cursor-crosshair select-none overflow-hidden rounded-tile bg-video-bg"
          >
            {failed ? (
              <p className="flex aspect-video items-center justify-center p-3 text-center text-sm text-text-muted">
                This frame could not be loaded. Close this and open it again to get a fresh link.
              </p>
            ) : (
              <img
                src={frame.imageUrl}
                alt={frame.label}
                draggable={false}
                onError={() => setFailed(true)}
                className="block max-h-[55vh] w-full object-contain"
              />
            )}
            {shown && (
              <div
                data-testid="crop-box"
                style={boxStyle(shown)}
                className="pointer-events-none absolute border-2 border-accent bg-accent/15"
              />
            )}
          </div>
        )}

        <div className="flex flex-wrap items-center gap-2">
          <Button
            type="button"
            disabled={!box || search.isPending}
            onClick={() =>
              search.mutate({ frame: frame.ref, bbox: toBbox(box), cameras: frame.cameras })
            }
          >
            {search.isPending ? 'Searching' : 'Find similar'}
          </Button>
          <Button
            type="button"
            variant="outline"
            disabled={search.isPending}
            onClick={() => {
              setBox({ x0: 0, y0: 0, x1: 1, y1: 1 });
              search.reset();
            }}
          >
            Use the whole frame
          </Button>
          {box && (
            <Button type="button" variant="ghost" onClick={() => setBox(null)}>
              Clear box
            </Button>
          )}
          {!box && !search.isPending && (
            <span className="text-sm text-text-muted">Draw a box to search.</span>
          )}
        </div>

        {search.isError && (
          <p role="alert" className="text-sm text-sev-critical">
            {errorMessage(search.error, {
              forbidden: 'You do not have access to search.',
              fallback: 'The search did not finish. Check your connection and try again.',
            })}
          </p>
        )}

        {search.isSuccess && (
          <section aria-label="Similar footage" className="flex flex-col gap-2">
            <p className="text-sm text-text-muted">
              {results.length === 0
                ? 'Nothing in the archive looks like that. Try a looser box or the whole frame.'
                : `${results.length} place${results.length > 1 ? 's' : ''} where something similar appears.`}
            </p>
            <div className="grid gap-3 sm:grid-cols-2">
              {results.map((result, index) => (
                <ResultCard
                  key={result.result_id}
                  result={result}
                  rank={index + 1}
                  searchId={search.data.search_id}
                  canFindSimilar={false}
                />
              ))}
            </div>
          </section>
        )}
      </DialogContent>
    </Dialog>
  );
}
