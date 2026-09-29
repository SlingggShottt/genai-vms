import { useState } from 'react';
import { Plus } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useCameras, useCreateCamera, useUpdateCamera } from '../api';
import { CameraForm } from '../components/CameraForm';

/** Admin-only camera CRUD (P1-J5 AC: list/add/edit/disable). Read access to
 * this route itself isn't role-gated at the router level yet — the API
 * enforces admin-only on write (create/update), so a non-admin sees the
 * list but any write attempt 403s.
 */
export function CamerasSettingsPage() {
  const { data, isLoading, isError } = useCameras();
  const createCamera = useCreateCamera();
  const updateCamera = useUpdateCamera();
  const [isAdding, setIsAdding] = useState(false);
  const [editingId, setEditingId] = useState(null);

  function handleCreate(values) {
    createCamera.mutate(values, { onSuccess: () => setIsAdding(false) });
  }

  function handleUpdate(id, values) {
    // code isn't editable (see CameraForm's disableCode) so it's dropped here.
    const { code: _code, ...editable } = values;
    updateCamera.mutate({ id, ...editable }, { onSuccess: () => setEditingId(null) });
  }

  function handleToggleEnabled(camera) {
    updateCamera.mutate({ id: camera.id, enabled: !camera.enabled });
  }

  return (
    <div className="p-6">
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-lg font-semibold text-text">Camera settings</h1>
        {!isAdding && (
          <Button size="sm" onClick={() => setIsAdding(true)}>
            <Plus size={16} aria-hidden="true" />
            Add camera
          </Button>
        )}
      </div>

      {isAdding && (
        <div className="mb-4">
          <CameraForm
            submitLabel="Add camera"
            onSubmit={handleCreate}
            onCancel={() => setIsAdding(false)}
            isSubmitting={createCamera.isPending}
          />
          {createCamera.isError && (
            <p role="alert" className="mt-2 text-sm text-sev-critical">
              {createCamera.error.message}
            </p>
          )}
        </div>
      )}

      {isLoading && <p className="text-sm text-text-muted">Loading cameras…</p>}
      {isError && <p className="text-sm text-sev-critical">Could not load cameras.</p>}

      {data && data.items.length === 0 && !isAdding && (
        <p className="text-sm text-text-muted">No cameras yet. Add a camera to start recording.</p>
      )}

      {data && data.items.length > 0 && (
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="border-b border-rule text-left text-text-muted">
              <th className="py-2 pr-4 font-medium">Code</th>
              <th className="py-2 pr-4 font-medium">Name</th>
              <th className="py-2 pr-4 font-medium">Site</th>
              <th className="py-2 pr-4 font-medium">Status</th>
              <th className="py-2 pr-4 font-medium">Actions</th>
            </tr>
          </thead>
          <tbody>
            {data.items.map((camera) =>
              editingId === camera.id ? (
                <tr key={camera.id}>
                  <td colSpan={5} className="py-3">
                    <CameraForm
                      initialValues={camera}
                      disableCode
                      submitLabel="Save changes"
                      onSubmit={(values) => handleUpdate(camera.id, values)}
                      onCancel={() => setEditingId(null)}
                      isSubmitting={updateCamera.isPending}
                    />
                  </td>
                </tr>
              ) : (
                <tr key={camera.id} className="border-b border-rule">
                  <td className="py-2 pr-4 text-text">{camera.code}</td>
                  <td className="py-2 pr-4 text-text">{camera.name}</td>
                  <td className="py-2 pr-4 text-text-muted">{camera.site_id}</td>
                  <td className="py-2 pr-4">
                    <span className={camera.enabled ? 'text-ok' : 'text-text-muted'}>
                      {camera.enabled ? 'Enabled' : 'Disabled'}
                    </span>
                  </td>
                  <td className="py-2 pr-4">
                    <div className="flex gap-2">
                      <Button size="sm" variant="outline" onClick={() => setEditingId(camera.id)}>
                        Edit
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => handleToggleEnabled(camera)}
                      >
                        {camera.enabled ? 'Disable' : 'Enable'}
                      </Button>
                    </div>
                  </td>
                </tr>
              ),
            )}
          </tbody>
        </table>
      )}
    </div>
  );
}
