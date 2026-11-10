import { colorToHex, colorToTone, type StatusRegistry } from '@/components/platform/status-badge';
import type { Idea } from '@/types/ideation';

/** A one-entry StatusBadge registry from the idea's engine-resolved status
 * (key + label + colour) - never a hardcoded status union. Shared by the list
 * Status column and the detail header pill. */
export function statusRegistryFor(idea: Idea): StatusRegistry<string> {
  const label = idea.statusLabel ?? idea.status;
  return {
    [idea.status]: {
      label,
      tone: colorToTone(idea.statusColor),
      hex: colorToHex(idea.statusColor),
    },
  };
}
