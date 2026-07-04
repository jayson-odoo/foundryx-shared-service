import {
  StatusBadge,
  type StatusBadgeProps,
} from '@/components/platform/status-badge/status-badge';
import { colorToHex, colorToTone } from '@/components/platform/status-badge/color-tone';

/**
 * A `StatusBadge` driven by a status-engine label + hex (the surfaces carry
 * `statusLabel`/`statusColor` straight off the engine, AC-06-08). Builds the
 * one-entry registry inline so every surface renders the lifecycle status
 * identically. Identity-agnostic — used by both worlds' submission/decision
 * displays.
 */
export interface EngineStatusBadgeProps {
  label: string;
  color: string | null | undefined;
  /** A stable key for the registry (the status id); defaults to the label. */
  statusKey?: string;
  size?: StatusBadgeProps<string>['size'];
  className?: string;
}

export function EngineStatusBadge({
  label,
  color,
  statusKey,
  size,
  className,
}: EngineStatusBadgeProps) {
  const key = statusKey ?? label;
  return (
    <StatusBadge
      status={key}
      registry={{
        [key]: {
          label,
          tone: colorToTone(color),
          hex: colorToHex(color),
        },
      }}
      size={size}
      className={className}
    />
  );
}
