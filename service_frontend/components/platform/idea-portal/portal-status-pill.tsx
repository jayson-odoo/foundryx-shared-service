import { StatusBadge, colorToHex, colorToTone, type StatusRegistry } from '@/components/platform/status-badge';

export interface PortalStatusPillProps {
  label: string;
  color: string | null;
}

/** The SAME `StatusBadge` pill the Ideas app uses; label/colour come from the
 * status engine (never hardcoded). */
export function PortalStatusPill({ label, color }: PortalStatusPillProps) {
  const registry: StatusRegistry<string> = {
    [label]: { label, tone: colorToTone(color), hex: colorToHex(color) },
  };
  return <StatusBadge status={label} registry={registry} />;
}
