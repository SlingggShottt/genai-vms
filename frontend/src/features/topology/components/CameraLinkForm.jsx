import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { linkProblems } from '../lib';
import { EDGE_TYPES, EDGE_TYPE_LABELS, MAX_TOLERANCE_S, MAX_TRANSIT_S } from '../schemas';

const SELECT_CLASS =
  'flex h-9 w-full rounded-panel border border-rule bg-surface px-3 py-1 text-sm text-text disabled:opacity-50';

const TYPE_HELP = {
  overlap: 'Both cameras see the same place at the same time.',
  transit: 'People leave one camera and show up in the other a little later.',
};

function FieldError({ id, children }) {
  if (!children) return null;
  return (
    <p id={id} className="text-xs text-sev-critical">
      {children}
    </p>
  );
}

function SecondsField({ id, label, value, onChange, error, max, ...rest }) {
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        type="number"
        inputMode="decimal"
        min={0}
        max={max}
        step="any"
        value={value}
        aria-invalid={Boolean(error)}
        aria-describedby={error ? `${id}-error` : undefined}
        onChange={(event) => onChange(event.target.value)}
        {...rest}
      />
      <FieldError id={`${id}-error`}>{error}</FieldError>
    </div>
  );
}

/** Add or edit one camera link (FR-CAM-04). The api treats a link's cameras and type as its
 * identity, so when editing only the timing and direction are open.
 */
export function CameraLinkForm({
  cameras,
  draft,
  onChange,
  onSubmit,
  onCancel,
  editing = false,
  isSaving = false,
  showErrors = false,
  error = null,
}) {
  const problems = showErrors ? linkProblems(draft, { editing }) : {};
  const set = (patch) => onChange({ ...draft, ...patch });

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
      noValidate
      className="flex flex-col gap-3 rounded-panel border border-rule bg-surface p-4"
    >
      <div className="grid grid-cols-2 gap-3">
        {[
          ['from', 'From camera', 'link-from'],
          ['to', 'To camera', 'link-to'],
        ].map(([field, label, id]) => (
          <div key={field} className="flex flex-col gap-1.5">
            <Label htmlFor={id}>{label}</Label>
            <select
              id={id}
              className={SELECT_CLASS}
              value={draft[field]}
              disabled={editing}
              aria-invalid={Boolean(problems[field])}
              aria-describedby={problems[field] ? `${id}-error` : undefined}
              onChange={(event) => set({ [field]: event.target.value })}
            >
              <option value="">Choose a camera</option>
              {cameras.map((camera) => (
                <option key={camera.id} value={camera.id}>
                  {camera.name} ({camera.code})
                </option>
              ))}
            </select>
            <FieldError id={`${id}-error`}>{problems[field]}</FieldError>
          </div>
        ))}
      </div>

      <fieldset className="flex flex-col gap-2" disabled={editing}>
        <legend className="mb-1 text-sm font-medium text-text">Type</legend>
        {EDGE_TYPES.map((type) => (
          <div key={type} className="flex items-start gap-2 text-sm text-text">
            <input
              id={`link-type-${type}`}
              type="radio"
              name="link-type"
              className="mt-0.5 h-4 w-4 accent-accent"
              value={type}
              checked={draft.type === type}
              onChange={() => set({ type })}
            />
            <label htmlFor={`link-type-${type}`}>
              <span className="font-medium">{EDGE_TYPE_LABELS[type]}</span>
              <span className="block text-text-muted">{TYPE_HELP[type]}</span>
            </label>
          </div>
        ))}
      </fieldset>
      {editing && (
        <p className="text-xs text-text-muted">
          To change the cameras or the type, delete this link and add a new one.
        </p>
      )}

      {draft.type === 'overlap' ? (
        <SecondsField
          id="link-tolerance"
          label="Time tolerance (seconds)"
          value={draft.tolerance}
          max={MAX_TOLERANCE_S}
          error={problems.tolerance}
          onChange={(tolerance) => set({ tolerance })}
        />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3">
            <SecondsField
              id="link-min"
              label="Shortest trip (seconds)"
              value={draft.min}
              max={MAX_TRANSIT_S}
              error={problems.min}
              onChange={(min) => set({ min })}
            />
            <SecondsField
              id="link-max"
              label="Longest trip (seconds)"
              value={draft.max}
              max={MAX_TRANSIT_S}
              error={problems.max}
              onChange={(max) => set({ max })}
            />
          </div>
          <label className="flex items-center gap-2 text-sm text-text">
            <input
              type="checkbox"
              className="h-4 w-4 accent-accent"
              checked={draft.both}
              onChange={(event) => set({ both: event.target.checked })}
            />
            People also make this trip the other way
          </label>
        </>
      )}

      {error && (
        <p role="alert" className="text-sm text-sev-critical">
          {error}
        </p>
      )}

      <div className="flex gap-2">
        <Button type="submit" size="sm" disabled={isSaving}>
          {isSaving ? 'Saving…' : editing ? 'Save changes' : 'Add link'}
        </Button>
        <Button type="button" size="sm" variant="outline" onClick={onCancel} disabled={isSaving}>
          Cancel
        </Button>
      </div>
    </form>
  );
}
