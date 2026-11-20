'use client';

import { cn } from '@/lib/utils';
import { useFx } from '@/hooks/use-fx';
import { FxHoldToCopy } from '@/components/fx/copy/hold-to-copy';

/** Red required marker - system-wide convention for required fields (plan 02 review). */
export function RequiredMark() {
  return (
    <span className="ms-0.5 text-destructive" aria-hidden="true">
      *
    </span>
  );
}

export interface FormRowProps {
  label: string;
  required?: boolean;
  children: React.ReactNode;
  className?: string;
}

/**
 * One label/value row in a Resource form. Read mode shows plain values; edit
 * mode passes inputs as children. Required fields render a `*` uniformly.
 */
export function FormRow(props: FormRowProps) {
  return useFx() ? <FxFormRow {...props} /> : <FormRowLegacy {...props} />;
}

/**
 * With the Foundryx UIUX switch on, a plain read-mode value (text or a
 * number) is Hold to Copy; inputs and other elements stay as they are,
 * since fields never copy.
 */
function FxFormRow({ children, ...rest }: FormRowProps) {
  const plain = typeof children === 'string' || typeof children === 'number';
  return (
    <FormRowLegacy {...rest}>{plain ? <FxHoldToCopy>{children}</FxHoldToCopy> : children}</FormRowLegacy>
  );
}

function FormRowLegacy({ label, required, children, className }: FormRowProps) {
  return (
    <div
      className={cn(
        'grid grid-cols-1 gap-1 border-b border-border py-3.5 last:border-0 sm:grid-cols-[200px_1fr] sm:items-center sm:gap-4',
        className,
      )}
    >
      <span className="text-sm text-muted-foreground">
        {label}
        {required && <RequiredMark />}
      </span>
      <div className="text-sm text-foreground">{children}</div>
    </div>
  );
}
