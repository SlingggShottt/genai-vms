import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { toast } from 'sonner';
import { apiClient } from '@/lib/apiClient';
import { PdfButton } from './PdfButton';

vi.mock('@/lib/apiClient', () => ({ apiClient: { get: vi.fn() } }));
vi.mock('sonner', () => ({ toast: vi.fn() }));

let clicked;
beforeEach(() => {
  clicked = [];
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function click() {
    clicked.push({ href: this.href, target: this.target, rel: this.rel });
  });
  apiClient.get.mockReset();
  toast.mockReset();
});
afterEach(() => vi.restoreAllMocks());

describe('PdfButton', () => {
  it('shows nothing for a report that has no PDF', () => {
    render(<PdfButton path="/incidents/1/pdf" available={false} />);
    expect(screen.queryByRole('button')).toBeNull();
  });

  it('asks for a fresh link when pressed and opens it in a new tab', async () => {
    apiClient.get.mockResolvedValue({
      url: 'https://media.example.org/vms-reports/x.pdf?sig=1',
      expires_in: 900,
    });
    render(<PdfButton path="/incidents/1/pdf" available />);
    expect(apiClient.get).not.toHaveBeenCalled(); // not before it is wanted: links expire
    fireEvent.click(screen.getByRole('button', { name: 'Download PDF' }));
    await waitFor(() => expect(clicked).toHaveLength(1));
    expect(apiClient.get).toHaveBeenCalledWith('/incidents/1/pdf');
    expect(clicked[0]).toMatchObject({
      href: 'https://media.example.org/vms-reports/x.pdf?sig=1',
      target: '_blank',
      rel: 'noopener',
    });
  });

  it('says so, and stays usable, when the link cannot be had', async () => {
    apiClient.get.mockRejectedValue(new Error('boom'));
    render(<PdfButton path="/incidents/1/pdf" available />);
    fireEvent.click(screen.getByRole('button', { name: 'Download PDF' }));
    await waitFor(() => expect(toast).toHaveBeenCalledWith('Could not get the PDF. Try again.'));
    expect(clicked).toHaveLength(0);
    expect(screen.getByRole('button', { name: 'Download PDF' }).disabled).toBe(false);
  });

  it('refuses an answer that is not a link', async () => {
    apiClient.get.mockResolvedValue({ url: 'javascript:alert(1)', expires_in: 900 });
    render(<PdfButton path="/incidents/1/pdf" available />);
    fireEvent.click(screen.getByRole('button', { name: 'Download PDF' }));
    await waitFor(() => expect(toast).toHaveBeenCalled());
    expect(clicked).toHaveLength(0);
  });
});
