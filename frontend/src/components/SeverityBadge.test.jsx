import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { SeverityBadge } from './SeverityBadge';

describe('SeverityBadge', () => {
  it.each([
    ['low', 'Low', 'circle'],
    ['medium', 'Medium', 'half-circle'],
    ['high', 'High', 'triangle'],
    ['critical', 'Critical', 'square'],
  ])('%s shows the label %s and the %s shape, not colour alone', (severity, label, shape) => {
    const { container } = render(<SeverityBadge severity={severity} />);
    expect(screen.getByText(label)).toBeInTheDocument();
    expect(container.querySelector(`svg[data-shape="${shape}"]`)).not.toBeNull();
    expect(container.querySelector('svg')).toHaveAttribute('aria-hidden', 'true');
  });

  it('uses its own severity colour for the text and a 16% tint behind it', () => {
    render(<SeverityBadge severity="high" />);
    const badge = screen.getByText('High').closest('[data-severity]');
    expect(badge.className).toContain('text-sev-high');
    expect(badge.className).toContain('bg-sev-high-tint');
  });

  it('never uses a raw colour', () => {
    const { container } = render(<SeverityBadge severity="critical" />);
    expect(container.innerHTML).not.toMatch(/#[0-9a-f]{3,8}\b|rgb\(/i);
  });
});
