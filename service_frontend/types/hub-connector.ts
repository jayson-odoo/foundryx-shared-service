/**
 * Hub Connector types - the wire shapes of `/hub-connector/*` (staff routes of
 * the `hub_connector` module). A hub is a partner platform that shows our stock
 * availability to its own customer companies.
 */

export interface Option {
  code: string;
  name: string;
}

export interface Hub {
  id: string;
  name: string;
  code: string;
  callbackUrl: string | null;
  exposePrice: boolean;
  active: boolean;
  customerCount: number;
  lastSuccessAt: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface HubCustomer {
  id: string;
  hubId: string;
  customerCode: string;
  customerName: string;
  locationCodes: string[];
  brandCodes: string[];
  locations: Option[];
  brands: Option[];
  active: boolean;
  updatedAt: string;
}

export type HubDeliveryStatus = 'PENDING' | 'SUCCESS' | 'FAILED';

export interface HubDelivery {
  id: string;
  event: string;
  customerCode: string;
  customerName: string;
  status: HubDeliveryStatus;
  attempt: number;
  lastCode: number | null;
  lastError: string | null;
  createdAt: string;
  lastAttemptAt: string | null;
}

export interface ApiKey {
  id: string;
  name: string;
  masked: string;
  createdAt: string;
  lastUsedAt: string | null;
  revokedAt: string | null;
}

/** Create answer - the full key, shown ONCE. */
export interface ApiKeyCreated extends ApiKey {
  key: string;
}

export interface Page<T> {
  data: T[];
  total: number;
  page?: number;
  pageSize?: number;
}

/** One row of the hub-facing view (snake_case: it is the hub contract). */
export interface PreviewItem {
  code: string;
  name: string;
  brand_name: string;
  in_stock: boolean;
  incoming: boolean;
  list_price?: number | null;
  currency?: string | null;
}

export interface CustomerPreview {
  items: PreviewItem[];
}

export interface HubCreateInput {
  name: string;
  code: string;
  callbackUrl: string;
}

export interface HubCreated {
  hub: Hub;
  signingSecret: string;
}

export interface HubUpdateInput {
  name?: string;
  callbackUrl?: string;
  exposePrice?: boolean;
  active?: boolean;
}

export interface HubCustomerCreateInput {
  customerCode: string;
  customerName: string;
  locationCodes: string[];
  brandCodes: string[];
}

export interface HubCustomerUpdateInput {
  customerName?: string;
  locationCodes?: string[];
  brandCodes?: string[];
  active?: boolean;
}

export type OptionKind = 'locations' | 'brands';

/** One scheduled background task of the Hub Connector. */
export interface ScheduledTask {
  key: string;
  name: string;
  schedule: string;
  lastRunAt: string | null;
  lastError: string | null;
}

/** State of the CRM stock feed sync. */
export interface SyncState {
  configured: boolean;
  lastRunAt: string | null;
  lastSuccessAt: string | null;
  lastError: string | null;
  products: number;
  queued: number;
}
