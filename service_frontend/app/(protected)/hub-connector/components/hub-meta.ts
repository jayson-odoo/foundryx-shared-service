import type { StatusRegistry } from '@/components/platform/status-badge';
import type { HubDeliveryStatus } from '@/types/hub-connector';
import type { FilterFieldDef } from '@/types/resource';

export const HUB_VIEW = 'hub_connector.view';
export const HUB_MANAGE = 'hub_connector.manage';
export const HUB_KEYS_MANAGE = 'hub_connector.keys.manage';
export const HUBS_PATH = '/hub-connector';

export const hubHref = (id: string): string => `${HUBS_PATH}/${encodeURIComponent(id)}`;

export type HubActiveStatus = 'ACTIVE' | 'INACTIVE';

export const HUB_ACTIVE_REGISTRY: StatusRegistry<HubActiveStatus> = {
  ACTIVE: { label: 'Active', tone: 'success' },
  INACTIVE: { label: 'Inactive', tone: 'secondary' },
};

export const hubActiveStatus = (active: boolean): HubActiveStatus => (active ? 'ACTIVE' : 'INACTIVE');

export const DELIVERY_STATUS_REGISTRY: StatusRegistry<HubDeliveryStatus> = {
  PENDING: { label: 'Waiting', tone: 'warning' },
  SUCCESS: { label: 'Delivered', tone: 'success' },
  FAILED: { label: 'Failed', tone: 'destructive' },
};

export const ACTIVE_FILTER: FilterFieldDef = {
  field: 'status',
  label: 'Status',
  type: 'enum',
  operators: ['in'],
  options: [
    { value: 'active', label: 'Active' },
    { value: 'inactive', label: 'Inactive' },
  ],
};

export const SHOW_PRICE_FILTER: FilterFieldDef = {
  field: 'showPrice',
  label: 'Show price',
  type: 'enum',
  operators: ['in'],
  options: [
    { value: 'yes', label: 'Yes' },
    { value: 'no', label: 'No' },
  ],
};

export const DELIVERY_STATUS_FILTER: FilterFieldDef = {
  field: 'status',
  label: 'Status',
  type: 'enum',
  operators: ['in'],
  options: Object.entries(DELIVERY_STATUS_REGISTRY).map(([value, meta]) => ({ value, label: meta.label })),
};
