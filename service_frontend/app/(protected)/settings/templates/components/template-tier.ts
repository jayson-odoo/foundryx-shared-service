import type { StatusRegistry } from '@/components/platform/status-badge';
import type { TemplateTier } from '@/types/templates';

/** Tier badge — Default (platform tier) vs Customized (tenant fork / own). */
export const TEMPLATE_TIER_REGISTRY: StatusRegistry<TemplateTier> = {
  default: { label: 'Default', tone: 'secondary' },
  customized: { label: 'Customized', tone: 'primary' },
};
