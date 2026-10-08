import { useState } from 'react';
import { Download } from 'lucide-react';
import { toast } from 'sonner';
import { z } from 'zod';
import { Button } from '@/components/ui/button';
import { apiClient } from '@/lib/apiClient';

// http(s) only: a `javascript:` or `data:` address is valid URL syntax and must not be opened.
const linkSchema = z.object({
  url: z
    .string()
    .url()
    .regex(/^https?:\/\//),
  expires_in: z.number(),
});

/** "Download PDF" for a report that has one stored (`available`). The api hands out a link that
 * works for fifteen minutes, so it is asked for when the button is pressed, never kept.
 * `path` is the api path of that link, e.g. `/incidents/<id>/pdf`.
 */
export function PdfButton({ path, available }) {
  const [busy, setBusy] = useState(false);
  if (!available) return null;

  async function open() {
    setBusy(true);
    try {
      const { url } = linkSchema.parse(await apiClient.get(path));
      const link = document.createElement('a');
      link.href = url;
      link.target = '_blank';
      link.rel = 'noopener';
      link.click();
    } catch {
      toast('Could not get the PDF. Try again.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <Button size="sm" onClick={open} disabled={busy} className="print:hidden">
      <Download size={14} aria-hidden="true" />
      Download PDF
    </Button>
  );
}
