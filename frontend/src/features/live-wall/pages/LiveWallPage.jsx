import { useMemo, useState } from 'react';
import { VideoTile } from '@/components/VideoTile';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { useCameraStatuses, useCameras } from '@/features/cameras/api';

const LAYOUTS = [1, 4, 6];

/** Merges the camera registry (name, code) with live status (online/
 * reconnecting/offline, polled every 5s) — VideoTile needs both.
 */
function useLiveWallCameras() {
  const { data: cameras } = useCameras();
  const { data: statuses } = useCameraStatuses();

  return useMemo(() => {
    if (!cameras) return [];
    const statusByCode = new Map((statuses?.cameras ?? []).map((s) => [s.code, s.status]));
    return cameras.items
      .filter((c) => c.enabled)
      .map((c) => ({ ...c, status: statusByCode.get(c.code) ?? 'offline' }));
  }, [cameras, statuses]);
}

export function LiveWallPage() {
  const cameras = useLiveWallCameras();
  const [layout, setLayout] = useState(4);
  const [focusedId, setFocusedId] = useState(null);

  const visibleCameras =
    layout === 1 && focusedId
      ? cameras.filter((c) => c.id === focusedId)
      : cameras.slice(0, layout);

  function handleDoubleClick(camera) {
    if (layout === 1) {
      setLayout(4);
      setFocusedId(null);
    } else {
      setFocusedId(camera.id);
      setLayout(1);
    }
  }

  if (cameras.length === 0) {
    return (
      <div className="flex h-full items-center justify-center text-center text-text-muted">
        <p>No cameras yet. Add a camera in Settings to start recording.</p>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col p-4">
      <div className="mb-4 flex items-center gap-1" role="group" aria-label="Camera wall layout">
        {LAYOUTS.map((n) => (
          <Button
            key={n}
            size="sm"
            variant={layout === n ? 'default' : 'outline'}
            onClick={() => {
              setLayout(n);
              setFocusedId(null);
            }}
          >
            {n === 1 ? '1 tile' : `${n} tiles`}
          </Button>
        ))}
      </div>

      <div
        className={cn(
          'grid flex-1 gap-2',
          layout === 1 && 'grid-cols-1',
          layout === 4 && 'grid-cols-2',
          layout === 6 && 'grid-cols-3',
        )}
      >
        {visibleCameras.map((camera) => (
          <VideoTile
            key={camera.id}
            camera={camera}
            focused={camera.id === focusedId}
            onDoubleClick={() => handleDoubleClick(camera)}
          />
        ))}
      </div>
    </div>
  );
}
