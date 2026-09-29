import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { cameraFormSchema } from '../schemas';

const EMPTY_VALUES = {
  code: '',
  name: '',
  rtsp_url: '',
  site_id: '',
  location_label: '',
  enabled: true,
};

/** Add/edit form for a camera — shared by both flows in CamerasSettingsPage.
 * `disableCode` locks the code field on edit (code is not in the API's
 * updatable-fields set, see services/api/src/api/adapters/cameras.py).
 */
export function CameraForm({
  initialValues,
  disableCode = false,
  submitLabel,
  onSubmit,
  onCancel,
  isSubmitting,
}) {
  const [values, setValues] = useState({ ...EMPTY_VALUES, ...initialValues });
  const [errors, setErrors] = useState({});

  function setField(field, value) {
    setValues((prev) => ({ ...prev, [field]: value }));
  }

  function handleSubmit(event) {
    event.preventDefault();
    const result = cameraFormSchema.safeParse(values);
    if (!result.success) {
      const fieldErrors = {};
      for (const issue of result.error.issues) {
        fieldErrors[issue.path[0]] = issue.message;
      }
      setErrors(fieldErrors);
      return;
    }
    setErrors({});
    onSubmit({
      ...result.data,
      location_label: result.data.location_label || null,
    });
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="grid grid-cols-2 gap-3 rounded-panel border border-rule bg-surface p-4"
    >
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="camera-code">Code</Label>
        <Input
          id="camera-code"
          value={values.code}
          disabled={disableCode}
          onChange={(e) => setField('code', e.target.value)}
        />
        {errors.code && <p className="text-xs text-sev-critical">{errors.code}</p>}
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="camera-name">Name</Label>
        <Input
          id="camera-name"
          value={values.name}
          onChange={(e) => setField('name', e.target.value)}
        />
        {errors.name && <p className="text-xs text-sev-critical">{errors.name}</p>}
      </div>

      <div className="col-span-2 flex flex-col gap-1.5">
        <Label htmlFor="camera-rtsp-url">RTSP URL</Label>
        <Input
          id="camera-rtsp-url"
          placeholder="rtsp://mediamtx:8554/cam01"
          value={values.rtsp_url}
          onChange={(e) => setField('rtsp_url', e.target.value)}
        />
        {errors.rtsp_url && <p className="text-xs text-sev-critical">{errors.rtsp_url}</p>}
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="camera-site">Site</Label>
        <Input
          id="camera-site"
          value={values.site_id}
          onChange={(e) => setField('site_id', e.target.value)}
        />
        {errors.site_id && <p className="text-xs text-sev-critical">{errors.site_id}</p>}
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="camera-location">Location label (optional)</Label>
        <Input
          id="camera-location"
          value={values.location_label ?? ''}
          onChange={(e) => setField('location_label', e.target.value)}
        />
      </div>

      <div className="col-span-2 flex items-center justify-end gap-2 pt-2">
        <Button type="button" variant="ghost" onClick={onCancel} disabled={isSubmitting}>
          Cancel
        </Button>
        <Button type="submit" disabled={isSubmitting}>
          {isSubmitting ? 'Saving…' : submitLabel}
        </Button>
      </div>
    </form>
  );
}
