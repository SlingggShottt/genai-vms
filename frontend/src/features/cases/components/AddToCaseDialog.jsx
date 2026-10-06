import { useState } from 'react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { useAddItem, useCases, useCreateCase } from '../api';

const NEW = '__new__';

/** "Save to case": bookmark one thing (an event, an incident report, a moment of footage, a
 * search) in an existing investigation or a new one, with an optional note. Operators and admins.
 *
 * @param {{item: {kind: string, label: string, ref?: string, camera_id?: string, ts_start?: string, ts_end?: string}|null, onClose: () => void}} props  `item` null = closed
 */
export function AddToCaseDialog({ item, onClose }) {
  const { data: cases } = useCases({ enabled: Boolean(item) });
  const create = useCreateCase();
  const add = useAddItem();
  const [choice, setChoice] = useState('');
  const [title, setTitle] = useState('');
  const [note, setNote] = useState('');
  const [error, setError] = useState(null);

  const selected = choice || (cases?.length ? cases[0].id : NEW);
  const busy = create.isPending || add.isPending;

  async function save(event) {
    event.preventDefault();
    setError(null);
    try {
      let caseId = selected;
      let caseTitle = cases?.find((c) => c.id === selected)?.title;
      if (selected === NEW) {
        const created = await create.mutateAsync({ title: title.trim() });
        caseId = created.id;
        caseTitle = created.title;
      }
      await add.mutateAsync({ caseId, item: { ...item, note: note.trim() || null } });
      toast(`Saved to “${caseTitle}”`);
      setNote('');
      setTitle('');
      onClose();
    } catch {
      setError('Could not save to the case. Check your connection and try again.');
    }
  }

  return (
    <Dialog open={Boolean(item)} onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <form onSubmit={save} className="flex flex-col gap-4">
          <DialogHeader>
            <DialogTitle>Save to case</DialogTitle>
            <DialogDescription>{item?.label}</DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-1">
            <Label htmlFor="case-choice">Case</Label>
            <select
              id="case-choice"
              value={selected}
              onChange={(e) => setChoice(e.target.value)}
              className="h-9 rounded-panel border border-rule bg-surface px-2 text-sm text-text"
            >
              {(cases ?? []).map((c) => (
                <option key={c.id} value={c.id}>
                  {c.title} ({c.item_count})
                </option>
              ))}
              <option value={NEW}>New case…</option>
            </select>
          </div>
          {selected === NEW && (
            <div className="flex flex-col gap-1">
              <Label htmlFor="case-title">Name of the new case</Label>
              <Input
                id="case-title"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="For example: Gate intrusion, 4 Oct"
                required
                maxLength={200}
              />
            </div>
          )}
          <div className="flex flex-col gap-1">
            <Label htmlFor="case-note">Note (optional)</Label>
            <Textarea
              id="case-note"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              rows={2}
              maxLength={4000}
            />
          </div>
          {error && (
            <p role="alert" className="text-sm text-sev-critical">
              {error}
            </p>
          )}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={busy || (selected === NEW && !title.trim())}>
              Save to case
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
