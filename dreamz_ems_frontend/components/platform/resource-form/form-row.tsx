import { cn } from '@/lib/utils';

/** Red required marker — system-wide convention for required fields (plan 02 review). */
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
export function FormRow({ label, required, children, className }: FormRowProps) {
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
