import { useState } from 'react';
import { Plus } from 'lucide-react';
import { toast } from 'sonner';
import { ConfirmDialog } from '@/components/ConfirmDialog';
import { Button } from '@/components/ui/button';
import { useCurrentUser } from '@/features/auth/api';
import { isAdmin } from '@/features/auth/schemas';
import { useCameras } from '@/features/cameras/api';
import { errorMessage } from '@/lib/errorMessage';
import { cn } from '@/lib/utils';
import { useCreateEdge, useDeleteEdge, useEdges, useUpdateEdge } from '../api';
import { CameraGraph } from '../components/CameraGraph';
import { CameraLinkForm } from '../components/CameraLinkForm';
import {
  canSaveLink,
  describeCameras,
  describeTiming,
  draftFromEdge,
  draftToCreatePayload,
  draftToUpdatePayload,
  newLinkDraft,
} from '../lib';
import { EDGE_TYPE_LABELS } from '../schemas';

const SAVE_ERRORS = {
  forbidden: 'Only admins can change camera links.',
  fallback: 'Could not save the link. Check your connection and try again.',
};
const DELETE_ERRORS = {
  forbidden: 'Only admins can delete camera links.',
  fallback: 'Could not delete the link. Check your connection and try again.',
};

/** Which cameras are next to each other and how long it takes to get between them (FR-CAM-04):
 * what the correlation service uses to decide that events on two cameras belong together.
 */
export function CameraLinksPage() {
  const { data: user } = useCurrentUser();
  const admin = isAdmin(user);
  const cameras = useCameras();
  const edges = useEdges();
  const createEdge = useCreateEdge();
  const updateEdge = useUpdateEdge();
  const deleteEdge = useDeleteEdge();

  const [mode, setMode] = useState(null); // null | { kind: 'new' } | { kind: 'edit', edgeId }
  const [draft, setDraft] = useState(newLinkDraft);
  const [showErrors, setShowErrors] = useState(false);
  const [pendingDelete, setPendingDelete] = useState(null);

  const cameraList = cameras.data?.items ?? [];
  const links = edges.data ?? [];
  const byId = new Map(cameraList.map((camera) => [camera.id, camera]));
  const labelOf = (id) => byId.get(id)?.code ?? 'unknown camera';
  const saving = mode?.kind === 'edit' ? updateEdge : createEdge;
  const editing = mode?.kind === 'edit';

  function begin(nextMode, nextDraft) {
    createEdge.reset();
    updateEdge.reset();
    setShowErrors(false);
    setDraft(nextDraft);
    setMode(nextMode);
  }
  const cancel = () => begin(null, newLinkDraft());

  function handleSave() {
    setShowErrors(true);
    if (!canSaveLink(draft, { editing })) return;
    const done = {
      onSuccess: () => {
        toast.success('Camera link saved');
        cancel();
      },
    };
    if (editing) updateEdge.mutate({ id: mode.edgeId, ...draftToUpdatePayload(draft) }, done);
    else createEdge.mutate(draftToCreatePayload(draft), done);
  }

  function handleDelete() {
    deleteEdge.mutate(pendingDelete.id, {
      onSuccess: () => {
        toast.success('Camera link deleted');
        setPendingDelete(null);
      },
    });
  }

  const loading = cameras.isLoading || edges.isLoading;
  const failed = cameras.isError || edges.isError;

  return (
    <div className="p-6">
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-lg font-semibold text-text">Camera links</h1>
        {admin && mode === null && cameraList.length >= 2 && (
          <Button type="button" size="sm" onClick={() => begin({ kind: 'new' }, newLinkDraft())}>
            <Plus size={16} aria-hidden="true" />
            Add link
          </Button>
        )}
      </div>
      <p className="mb-4 max-w-2xl text-sm text-text-muted">
        Tell the system which cameras see the same place or lead to each other, so events that
        happen close together on linked cameras are grouped into one incident.
      </p>

      {loading && <p className="text-sm text-text-muted">Loading camera links…</p>}
      {failed && <p className="text-sm text-sev-critical">Could not load camera links.</p>}

      {!loading && !failed && cameraList.length < 2 && (
        <p className="text-sm text-text-muted">
          Camera links connect two cameras. Add at least two cameras first.
        </p>
      )}

      {!loading && !failed && cameraList.length >= 2 && (
        <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,32rem)]">
          <section aria-label="Links">
            {mode !== null && (
              <div className="mb-4">
                <CameraLinkForm
                  cameras={cameraList}
                  draft={draft}
                  onChange={setDraft}
                  onSubmit={handleSave}
                  onCancel={cancel}
                  editing={editing}
                  isSaving={saving.isPending}
                  showErrors={showErrors}
                  error={saving.isError ? errorMessage(saving.error, SAVE_ERRORS) : null}
                />
              </div>
            )}

            {links.length === 0 && mode === null && (
              <p className="text-sm text-text-muted">
                {admin
                  ? 'No camera links yet. Add a link so events on neighbouring cameras can be grouped.'
                  : 'No camera links yet.'}
              </p>
            )}

            {links.length > 0 && (
              <table className="w-full border-collapse text-sm">
                <thead>
                  <tr className="border-b border-rule text-left text-text-muted">
                    <th className="py-2 pr-4 font-medium">Cameras</th>
                    <th className="py-2 pr-4 font-medium">Type</th>
                    <th className="py-2 pr-4 font-medium">Timing</th>
                    {admin && <th className="py-2 font-medium">Actions</th>}
                  </tr>
                </thead>
                <tbody>
                  {links.map((edge) => {
                    const name = describeCameras(edge, labelOf);
                    return (
                      <tr
                        key={edge.id}
                        className={cn(
                          'border-b border-rule',
                          mode?.edgeId === edge.id && 'bg-surface-raised',
                        )}
                      >
                        <td className="py-2 pr-4 text-text">{name}</td>
                        <td className="py-2 pr-4 text-text">{EDGE_TYPE_LABELS[edge.edge_type]}</td>
                        <td className="py-2 pr-4 tabular-nums text-text-muted">
                          {describeTiming(edge)}
                        </td>
                        {admin && (
                          <td className="py-2">
                            <div className="flex gap-2">
                              <Button
                                type="button"
                                size="sm"
                                variant="outline"
                                aria-label={`Edit ${name}`}
                                disabled={mode !== null}
                                onClick={() =>
                                  begin({ kind: 'edit', edgeId: edge.id }, draftFromEdge(edge))
                                }
                              >
                                Edit
                              </Button>
                              <Button
                                type="button"
                                size="sm"
                                variant="outline"
                                aria-label={`Delete ${name}`}
                                disabled={mode !== null}
                                onClick={() => {
                                  deleteEdge.reset();
                                  setPendingDelete(edge);
                                }}
                              >
                                Delete
                              </Button>
                            </div>
                          </td>
                        )}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
            {!admin && (
              <p className="mt-3 text-sm text-text-muted">Only admins can change camera links.</p>
            )}
          </section>

          <section aria-label="Diagram">
            <CameraGraph
              cameras={cameraList}
              edges={links}
              selectedId={editing ? mode.edgeId : null}
            />
            <p className="mt-2 text-xs text-text-muted">
              Dashed: overlap, the cameras see the same place. Solid with an arrow: transit, the
              direction people travel. The number is the timing in seconds.
            </p>
          </section>
        </div>
      )}

      <ConfirmDialog
        open={pendingDelete !== null}
        title="Delete camera link"
        description={
          pendingDelete
            ? `Delete the link ${describeCameras(pendingDelete, labelOf)}? Events on these cameras will no longer be grouped by it.`
            : ''
        }
        confirmLabel="Delete link"
        onConfirm={handleDelete}
        onClose={() => setPendingDelete(null)}
        isPending={deleteEdge.isPending}
        error={deleteEdge.isError ? errorMessage(deleteEdge.error, DELETE_ERRORS) : null}
      />
    </div>
  );
}
