import type { StatusRegistry } from '@/components/platform/status-badge';
import type { TemplateStatus } from '@/types/whatsapp-template';

/**
 * WhatsApp template status pills (plan 07 UX-3) — frontend-only registry, NOT
 * the status engine (Meta owns the enum + drives transitions externally, T2).
 */
export const TEMPLATE_STATUS_REGISTRY: StatusRegistry<TemplateStatus> = {
  LOCAL_DRAFT: { label: 'Draft', tone: 'secondary' },
  PENDING: { label: 'Pending', tone: 'warning' },
  APPROVED: { label: 'Approved', tone: 'success' },
  REJECTED: { label: 'Rejected', tone: 'destructive' },
  PAUSED: { label: 'Paused', tone: 'secondary' },
  DISABLED: { label: 'Disabled', tone: 'secondary' },
};

export const TEMPLATE_CATEGORY_OPTIONS = [
  { label: 'Marketing', value: 'MARKETING' },
  { label: 'Utility', value: 'UTILITY' },
];

export const TEMPLATE_STATUS_OPTIONS = [
  { label: 'Draft', value: 'LOCAL_DRAFT' },
  { label: 'Pending', value: 'PENDING' },
  { label: 'Approved', value: 'APPROVED' },
  { label: 'Rejected', value: 'REJECTED' },
  { label: 'Paused', value: 'PAUSED' },
  { label: 'Disabled', value: 'DISABLED' },
];
