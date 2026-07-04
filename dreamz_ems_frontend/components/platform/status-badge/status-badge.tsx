import { Badge, BadgeDot } from '@/components/ui/badge';

/**
 * Uniform status pill used across the WHOLE system. Every entity declares a
 * `StatusRegistry` mapping its status values to a label + tone; `StatusBadge`
 * renders them identically (light pill + colored dot) so status reads the same
 * everywhere. See plan 02 §3 "design language".
 */

export type StatusTone = 'success' | 'warning' | 'info' | 'destructive' | 'secondary' | 'primary';

export interface StatusMeta {
  label: string;
  tone: StatusTone;
  /** Exact dot color (engine-picked hex) — overrides the tone's dot color. */
  hex?: string;
}

/** Maps each status value of an entity to its display meta. */
export type StatusRegistry<T extends string> = Record<T, StatusMeta>;

export interface StatusBadgeProps<T extends string> {
  status: T;
  registry: StatusRegistry<T>;
  size?: 'sm' | 'md' | 'lg';
  className?: string;
}

export function StatusBadge<T extends string>({
  status,
  registry,
  size = 'md',
  className,
}: StatusBadgeProps<T>) {
  const meta = registry[status];
  // Unknown status: degrade gracefully rather than crash a whole row.
  if (!meta) {
    return (
      <Badge variant="secondary" appearance="light" size={size} className={className}>
        {status}
      </Badge>
    );
  }

  return (
    <Badge variant={meta.tone} appearance="light" size={size} className={className}>
      <BadgeDot style={meta.hex ? { backgroundColor: meta.hex } : undefined} />
      {meta.label}
    </Badge>
  );
}
