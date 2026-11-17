'use client';

/** Empty-state for tabs whose content lands in a later slice (Grill = S3,
 * Trace = S4). Foolproof-UI: a short status line, never how-to copy. */
export function BrPlaceholderTab({ label }: { label: string }) {
  return (
    <p className="py-16 text-center text-sm text-muted-foreground">{label}</p>
  );
}
