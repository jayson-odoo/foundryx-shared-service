import { StatusBadge, type StatusRegistry } from '@/components/platform/status-badge';
import type { ContactLifecycleSummary } from '@/types/omnichannel';

/**
 * Lifecycle column cell (AC-CTM-02) - a StatusBadge-style chip carrying the
 * stage's OWN label + colour (tenant-authored on the canvas, plan 25), never
 * a hardcoded palette. `null` = the entity hasn't adopted the engine yet
 * (pre-migration) - renders a plain dash rather than crashing the row.
 */
export function ContactLifecycleCell({ lifecycle }: { lifecycle: ContactLifecycleSummary | null }) {
  if (!lifecycle) return <span className="text-muted-foreground">-</span>;
  const registry: StatusRegistry<string> = {
    [lifecycle.key]: { label: lifecycle.label, tone: 'secondary', hex: lifecycle.color ?? undefined },
  };
  return <StatusBadge status={lifecycle.key} registry={registry} size="sm" />;
}
