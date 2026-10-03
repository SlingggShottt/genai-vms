import { useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Plus } from 'lucide-react';
import { toast } from 'sonner';
import { ConfirmDialog } from '@/components/ConfirmDialog';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { isAdmin } from '@/features/auth/schemas';
import { useCurrentUser } from '@/features/auth/api';
import { useCameraStatuses, useCameras } from '@/features/cameras/api';
import { errorMessage } from '@/lib/errorMessage';
import { cn } from '@/lib/utils';
import { useCreateZone, useDeleteZone, useUpdateZone, useZones } from '../api';
import { FrameCapture } from '../components/FrameCapture';
import { PolygonEditor } from '../components/PolygonEditor';
import { ZoneForm } from '../components/ZoneForm';
import { canSave, describeSchedule, draftFromZone, draftToPayload, newDraft } from '../lib';
import { ZONE_TYPE_LABELS } from '../schemas';

const SAVE_ERRORS = {
  forbidden: 'Only admins can change zones.',
  fallback: 'Could not save the zone. Check your connection and try again.',
};
const DELETE_ERRORS = {
  forbidden: 'Only admins can delete zones.',
  fallback: 'Could not delete the zone. Check your connection and try again.',
};

/** Zones for one camera (FR-CAM-03): draw an outline over a frame of its live view, name it, say
 * what kind of place it is and, if it has normal hours, when. Keyed by camera so that switching
 * camera starts clean (no frame, no half-drawn outline).
 */
function CameraZones({ camera, status, admin }) {
  const zones = useZones(camera.id);
  const createZone = useCreateZone(camera.id);
  const updateZone = useUpdateZone(camera.id);
  const deleteZone = useDeleteZone(camera.id);

  const [frame, setFrame] = useState(null);
  const [mode, setMode] = useState(null); // null | { kind: 'new' } | { kind: 'edit', zoneId }
  const [draft, setDraft] = useState(newDraft);
  const [showErrors, setShowErrors] = useState(false);
  const [pendingDelete, setPendingDelete] = useState(null);

  // The frame is a blob URL this page created: free it when replaced and when leaving.
  const frameUrl = useRef(null);
  function replaceFrame(next) {
    if (frameUrl.current) URL.revokeObjectURL(frameUrl.current);
    frameUrl.current = next?.url ?? null;
    setFrame(next);
  }
  useEffect(
    () => () => {
      if (frameUrl.current) URL.revokeObjectURL(frameUrl.current);
    },
    [],
  );

  const items = zones.data ?? [];
  const saving = mode?.kind === 'edit' ? updateZone : createZone;
  const aspect = frame ? frame.width / frame.height : 16 / 9;

  function begin(nextMode, nextDraft) {
    createZone.reset();
    updateZone.reset();
    setShowErrors(false);
    setDraft(nextDraft);
    setMode(nextMode);
  }
  const cancel = () => begin(null, newDraft());

  function handleSave() {
    setShowErrors(true);
    if (!canSave(draft)) return;
    const payload = draftToPayload(draft);
    const done = {
      onSuccess: () => {
        toast.success('Zone saved');
        cancel();
      },
    };
    if (mode.kind === 'edit') updateZone.mutate({ id: mode.zoneId, ...payload }, done);
    else createZone.mutate(payload, done);
  }

  function handleDelete() {
    deleteZone.mutate(pendingDelete.id, {
      onSuccess: () => {
        toast.success('Zone deleted');
        setPendingDelete(null);
      },
    });
  }

  const editingId = mode?.kind === 'edit' ? mode.zoneId : null;
  const otherZones = items.filter((zone) => zone.id !== editingId);

  return (
    <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
      {admin && (
        <section aria-label="Camera frame">
          {frame ? (
            <>
              <PolygonEditor
                frameUrl={frame.url}
                aspect={aspect}
                points={draft.points}
                onChange={(points) => setDraft((current) => ({ ...current, points }))}
                otherZones={otherZones}
                disabled={mode === null}
              />
              <div className="mt-2 flex items-center gap-3">
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={() => replaceFrame(null)}
                >
                  Capture a new frame
                </Button>
                {mode === null && (
                  <p className="text-sm text-text-muted">
                    Add a zone, or edit one, to draw on this frame.
                  </p>
                )}
              </div>
            </>
          ) : (
            <FrameCapture
              camera={camera}
              status={status}
              onCapture={replaceFrame}
              hint="Capture a still from the live view to draw zones on."
            />
          )}
        </section>
      )}

      <section aria-label="Zones" className={cn(!admin && 'max-w-xl')}>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-base font-semibold text-text">Zones on {camera.name}</h2>
          {admin && mode === null && (
            <Button type="button" size="sm" onClick={() => begin({ kind: 'new' }, newDraft())}>
              <Plus size={16} aria-hidden="true" />
              Add zone
            </Button>
          )}
        </div>

        {mode !== null && (
          <div className="mb-4">
            {!frame && (
              <p className="mb-2 text-sm text-text-muted">
                Capture a frame first, then draw the outline on it.
              </p>
            )}
            <ZoneForm
              draft={draft}
              onChange={setDraft}
              onSubmit={handleSave}
              onCancel={cancel}
              isSaving={saving.isPending}
              showErrors={showErrors}
              submitLabel={mode.kind === 'edit' ? 'Save changes' : 'Save zone'}
              error={saving.isError ? errorMessage(saving.error, SAVE_ERRORS) : null}
            />
          </div>
        )}

        {zones.isLoading && <p className="text-sm text-text-muted">Loading zones…</p>}
        {zones.isError && <p className="text-sm text-sev-critical">Could not load zones.</p>}
        {zones.isSuccess && items.length === 0 && mode === null && (
          <p className="text-sm text-text-muted">
            {admin
              ? 'No zones yet. Add a zone to tell the system where to watch.'
              : 'No zones on this camera yet.'}
          </p>
        )}

        {items.length > 0 && (
          <ul className="flex flex-col divide-y divide-rule border-y border-rule">
            {items.map((zone) => (
              <li
                key={zone.id}
                className={cn(
                  'flex items-start justify-between gap-3 py-3',
                  zone.id === editingId && 'bg-surface-raised',
                )}
              >
                <div className="min-w-0">
                  <p className="truncate font-medium text-text">{zone.name}</p>
                  <p className="text-sm text-text-muted">
                    {ZONE_TYPE_LABELS[zone.zone_type]} · {zone.polygon.length} points
                  </p>
                  <p className="text-sm text-text-muted">
                    Normal hours: {describeSchedule(zone.schedule)}
                  </p>
                </div>
                {admin && (
                  <div className="flex shrink-0 gap-2">
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      aria-label={`Edit ${zone.name}`}
                      disabled={mode !== null}
                      onClick={() => begin({ kind: 'edit', zoneId: zone.id }, draftFromZone(zone))}
                    >
                      Edit
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      aria-label={`Delete ${zone.name}`}
                      disabled={mode !== null}
                      onClick={() => {
                        deleteZone.reset();
                        setPendingDelete(zone);
                      }}
                    >
                      Delete
                    </Button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}

        {!admin && <p className="mt-3 text-sm text-text-muted">Only admins can change zones.</p>}
      </section>

      <ConfirmDialog
        open={pendingDelete !== null}
        title="Delete zone"
        description={
          pendingDelete
            ? `Delete “${pendingDelete.name}” from ${camera.name}? This can't be undone.`
            : ''
        }
        confirmLabel="Delete zone"
        onConfirm={handleDelete}
        onClose={() => setPendingDelete(null)}
        isPending={deleteZone.isPending}
        error={deleteZone.isError ? errorMessage(deleteZone.error, DELETE_ERRORS) : null}
      />
    </div>
  );
}

export function ZonesPage() {
  const { data: user } = useCurrentUser();
  const cameras = useCameras();
  const statuses = useCameraStatuses();
  const [searchParams, setSearchParams] = useSearchParams();

  const items = cameras.data?.items ?? [];
  const camera = items.find((c) => c.id === searchParams.get('camera')) ?? items[0];
  const status = statuses.data?.cameras.find((c) => c.id === camera?.id)?.status;

  return (
    <div className="p-6">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-lg font-semibold text-text">Zones</h1>
        {items.length > 0 && (
          <div className="flex items-center gap-2">
            <Label htmlFor="zones-camera">Camera</Label>
            <select
              id="zones-camera"
              className="flex h-9 rounded-panel border border-rule bg-surface px-3 py-1 text-sm text-text"
              value={camera.id}
              onChange={(event) => setSearchParams({ camera: event.target.value })}
            >
              {items.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name} ({c.code})
                </option>
              ))}
            </select>
          </div>
        )}
      </div>

      {cameras.isLoading && <p className="text-sm text-text-muted">Loading cameras…</p>}
      {cameras.isError && <p className="text-sm text-sev-critical">Could not load cameras.</p>}
      {cameras.isSuccess && items.length === 0 && (
        <p className="text-sm text-text-muted">
          No cameras yet. Add a camera before drawing zones.
        </p>
      )}
      {camera && (
        <CameraZones key={camera.id} camera={camera} status={status} admin={isAdmin(user)} />
      )}
    </div>
  );
}
