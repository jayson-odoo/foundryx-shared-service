import type { StatusRegistry } from '@/components/platform/status-badge';
import { colorToHex, colorToTone } from '@/components/platform/status-badge';
import type { TenantLifecycle, TenantListItem } from '@/types/tenant-admin';

/**
 * Tenant status display (sprint-2/01) - engine-driven: render the server's
 * editable {statusLabel, statusColor} when present. The static registry is
 * only the fallback for older payloads (pre-engine sessions).
 */
export const TENANT_STATUS_REGISTRY: StatusRegistry<TenantLifecycle> = {
  ACTIVE: { label: 'Active', tone: 'success' },
  SUSPENDED: { label: 'Suspended', tone: 'warning' },
  ARCHIVED: { label: 'Archived', tone: 'secondary' },
};

/** One-row registry for a tenant - server label/color first, fallback static. */
export function tenantStatusRegistry(
  tenant: Pick<TenantListItem, 'status' | 'statusLabel' | 'statusColor'>,
): StatusRegistry<string> {
  if (tenant.statusLabel) {
    return {
      [tenant.status]: {
        label: tenant.statusLabel,
        tone: colorToTone(tenant.statusColor),
        hex: colorToHex(tenant.statusColor),
      },
    };
  }
  return TENANT_STATUS_REGISTRY as StatusRegistry<string>;
}
