import type { ReactNode } from 'react';

/**
 * One label/value row in the company Overview. Shared so the read-only identity
 * fields and the (edit-toggled) push-target fields render on the SAME grid - the
 * push target is part of the one Resource form, not a bespoke card (AC-15-21).
 */
export function DetailRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-1 gap-1 border-b border-border py-3 last:border-0 sm:grid-cols-[220px_1fr] sm:items-center sm:gap-4">
      <span className="text-sm text-muted-foreground">{label}</span>
      <div className="min-w-0 text-sm text-foreground">{children}</div>
    </div>
  );
}
