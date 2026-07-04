import type { StatusRegistry } from '@/components/platform/status-badge';
import type { ApiKeyStatus } from '@/types/api-keys';

/**
 * API-key status pills — frontend-only registry (the key lifecycle is a plain
 * ACTIVE/REVOKED flag on the row, not the status engine). Active = live/green,
 * Revoked = muted.
 */
export const API_KEY_STATUS_REGISTRY: StatusRegistry<ApiKeyStatus> = {
  ACTIVE: { label: 'Active', tone: 'success' },
  REVOKED: { label: 'Revoked', tone: 'secondary' },
};

export const API_KEY_STATUS_OPTIONS = [
  { label: 'Active', value: 'ACTIVE' },
  { label: 'Revoked', value: 'REVOKED' },
];
