import * as React from 'react';
import { cn } from '@/lib/utils';

export const Label = React.forwardRef(({ className, ...props }, ref) => (
  // htmlFor comes through `...props` from the caller (e.g. <Label htmlFor="email">) —
  // the a11y rule can't see through that spread to verify it, but every call site
  // in this codebase passes one.
  // eslint-disable-next-line jsx-a11y/label-has-associated-control
  <label
    ref={ref}
    className={cn('text-sm font-medium leading-none text-text', className)}
    {...props}
  />
));
Label.displayName = 'Label';
