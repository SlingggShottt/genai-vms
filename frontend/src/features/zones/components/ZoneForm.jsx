import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { cn } from '@/lib/utils';
import { canSave, draftProblems } from '../lib';
import { DAYS, DAY_LABELS, ZONE_TYPES, ZONE_TYPE_LABELS } from '../schemas';

const SELECT_CLASS =
  'flex h-9 w-full rounded-panel border border-rule bg-surface px-3 py-1 text-sm text-text disabled:opacity-50';

function FieldError({ id, children }) {
  if (!children) return null;
  return (
    <p id={id} className="text-xs text-sev-critical">
      {children}
    </p>
  );
}

/** The details of one zone: name, type and optional normal hours (FR-CAM-03). The outline is
 * drawn in the PolygonEditor beside it; this form only reports what is wrong with it.
 *
 * Errors for a field show once the person has tried to save (`showErrors`), not while they are
 * still typing the first letter. Save stays enabled so that trying it says what is missing.
 */
export function ZoneForm({
  draft,
  onChange,
  onSubmit,
  onCancel,
  isSaving = false,
  showErrors = false,
  submitLabel = 'Save zone',
  error = null,
}) {
  const { details, outline } = draftProblems(draft);
  const set = (patch) => onChange({ ...draft, ...patch });
  const setSchedule = (patch) => onChange({ ...draft, schedule: { ...draft.schedule, ...patch } });
  const shown = (field) => (showErrors ? details[field] : undefined);

  function toggleDay(day) {
    const days = draft.schedule.days.includes(day)
      ? draft.schedule.days.filter((d) => d !== day)
      : [...draft.schedule.days, day];
    setSchedule({ days });
  }

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
      noValidate
      className="flex flex-col gap-3 rounded-panel border border-rule bg-surface p-4"
    >
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="zone-name">Name</Label>
        <Input
          id="zone-name"
          value={draft.name}
          maxLength={200}
          aria-invalid={Boolean(shown('name'))}
          aria-describedby={shown('name') ? 'zone-name-error' : undefined}
          onChange={(event) => set({ name: event.target.value })}
        />
        <FieldError id="zone-name-error">{shown('name')}</FieldError>
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="zone-type">Type</Label>
        <select
          id="zone-type"
          className={SELECT_CLASS}
          value={draft.zone_type}
          onChange={(event) => set({ zone_type: event.target.value })}
        >
          {ZONE_TYPES.map((type) => (
            <option key={type} value={type}>
              {ZONE_TYPE_LABELS[type]}
            </option>
          ))}
        </select>
      </div>

      <fieldset className="flex flex-col gap-2">
        <legend className="sr-only">Normal hours</legend>
        <label className="flex items-center gap-2 text-sm text-text">
          <input
            type="checkbox"
            className="h-4 w-4 accent-accent"
            checked={draft.scheduled}
            onChange={(event) => set({ scheduled: event.target.checked })}
          />
          Set normal hours
        </label>
        {draft.scheduled && (
          <div className="flex flex-col gap-3 pl-6">
            <p className="text-xs text-text-muted">
              People in this zone outside these hours raise an after-hours alert. Site time; the
              window can run past midnight.
            </p>
            <div className="flex gap-3">
              <div className="flex flex-1 flex-col gap-1.5">
                <Label htmlFor="zone-start">From</Label>
                <Input
                  id="zone-start"
                  type="time"
                  value={draft.schedule.start_time}
                  aria-invalid={Boolean(shown('start_time'))}
                  onChange={(event) => setSchedule({ start_time: event.target.value })}
                />
                <FieldError>{shown('start_time')}</FieldError>
              </div>
              <div className="flex flex-1 flex-col gap-1.5">
                <Label htmlFor="zone-end">To</Label>
                <Input
                  id="zone-end"
                  type="time"
                  value={draft.schedule.end_time}
                  aria-invalid={Boolean(shown('end_time'))}
                  onChange={(event) => setSchedule({ end_time: event.target.value })}
                />
                <FieldError>{shown('end_time')}</FieldError>
              </div>
            </div>
            <fieldset className="flex flex-col gap-1.5">
              <legend className="text-sm font-medium text-text">Days</legend>
              <div className="flex flex-wrap gap-1.5">
                {DAYS.map((day) => {
                  const on = draft.schedule.days.includes(day);
                  return (
                    <label
                      key={day}
                      className={cn(
                        'flex h-8 cursor-pointer items-center rounded-panel border px-2 text-sm',
                        'focus-within:ring-2 focus-within:ring-accent',
                        on
                          ? 'border-accent bg-accent-tint text-text'
                          : 'border-rule text-text-muted hover:text-text',
                      )}
                    >
                      <input
                        type="checkbox"
                        className="sr-only"
                        checked={on}
                        onChange={() => toggleDay(day)}
                      />
                      {DAY_LABELS[day]}
                    </label>
                  );
                })}
              </div>
              <FieldError>{shown('days')}</FieldError>
            </fieldset>
          </div>
        )}
      </fieldset>

      {showErrors && outline.length > 0 && (
        <ul role="alert" className="list-disc pl-4 text-sm text-sev-critical">
          {outline.map((message) => (
            <li key={message}>{message}</li>
          ))}
        </ul>
      )}
      {error && (
        <p role="alert" className="text-sm text-sev-critical">
          {error}
        </p>
      )}

      <div className="flex gap-2">
        <Button type="submit" size="sm" disabled={isSaving}>
          {isSaving ? 'Saving…' : submitLabel}
        </Button>
        <Button type="button" size="sm" variant="outline" onClick={onCancel} disabled={isSaving}>
          Cancel
        </Button>
      </div>
      {!canSave(draft) && !showErrors && (
        <p className="text-xs text-text-muted">
          Draw the outline on the frame, then name the zone.
        </p>
      )}
    </form>
  );
}
