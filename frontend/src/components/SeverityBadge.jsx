import { cn } from '@/lib/utils';

/** Severity is shown with colour + label + shape, never colour alone (§B.3): low ○, medium ◐,
 * high ▲, critical ■. The tint is 16% of the severity colour, the text the full colour (§B.7).
 */
export const SEVERITY_META = {
  low: { label: 'Low', pill: 'bg-sev-low-tint text-sev-low', bar: 'border-sev-low' },
  medium: { label: 'Medium', pill: 'bg-sev-medium-tint text-sev-medium', bar: 'border-sev-medium' },
  high: { label: 'High', pill: 'bg-sev-high-tint text-sev-high', bar: 'border-sev-high' },
  critical: {
    label: 'Critical',
    pill: 'bg-sev-critical-tint text-sev-critical',
    bar: 'border-sev-critical',
  },
};

function SeverityShape({ severity }) {
  const common = { width: 12, height: 12, viewBox: '0 0 12 12', 'aria-hidden': true };
  switch (severity) {
    case 'low':
      return (
        <svg {...common} data-shape="circle">
          <circle cx="6" cy="6" r="4.5" fill="none" stroke="currentColor" strokeWidth="1.5" />
        </svg>
      );
    case 'medium':
      return (
        <svg {...common} data-shape="half-circle">
          <circle cx="6" cy="6" r="4.5" fill="none" stroke="currentColor" strokeWidth="1.5" />
          <path d="M6 1.5 A4.5 4.5 0 0 1 6 10.5 Z" fill="currentColor" />
        </svg>
      );
    case 'high':
      return (
        <svg {...common} data-shape="triangle">
          <path d="M6 1 L11.5 10.5 L0.5 10.5 Z" fill="currentColor" />
        </svg>
      );
    default:
      return (
        <svg {...common} data-shape="square">
          <rect x="1.5" y="1.5" width="9" height="9" fill="currentColor" />
        </svg>
      );
  }
}

export function SeverityBadge({ severity, className }) {
  const meta = SEVERITY_META[severity] ?? SEVERITY_META.low;
  return (
    <span
      data-severity={severity}
      className={cn(
        'inline-flex items-center gap-1 rounded-pill px-2 py-px text-xs font-medium',
        meta.pill,
        className,
      )}
    >
      <SeverityShape severity={severity} />
      {meta.label}
    </span>
  );
}
