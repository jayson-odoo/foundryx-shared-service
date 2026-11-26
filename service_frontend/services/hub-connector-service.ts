/**
 * Hub Connector service - the boundary the Hub Connector screens talk to. The
 * barrel binds the REAL api-client implementation; the in-memory mock
 * (`hub-connector-service.mock.ts`) stays for tests and a dev toggle. Every
 * call is the signed-in company's own data (the backend scopes by the JWT).
 */
import type {
  ApiKey,
  ApiKeyCreated,
  CustomerPreview,
  Hub,
  HubCreateInput,
  HubCreated,
  HubCustomer,
  HubCustomerCreateInput,
  HubCustomerUpdateInput,
  HubDelivery,
  HubDeliveryStatus,
  HubUpdateInput,
  Option,
  OptionKind,
  Page,
} from '@/types/hub-connector';
import type { ListQuery } from '@/types/resource';
import { realHubConnectorService } from './hub-connector-service.real';

export interface HubConnectorService {
  listHubs(query: ListQuery): Promise<Page<Hub>>;
  /** Returns the signing secret ONCE. */
  createHub(input: HubCreateInput): Promise<HubCreated>;
  getHub(id: string): Promise<Hub>;
  updateHub(id: string, input: HubUpdateInput): Promise<Hub>;
  deleteHub(id: string): Promise<void>;
  /** Returns the new signing secret ONCE. */
  rotateSecret(id: string): Promise<{ signingSecret: string }>;
  /** Queue every customer's full view again. */
  resync(id: string): Promise<{ queued: number }>;

  listCustomers(hubId: string, query: ListQuery): Promise<Page<HubCustomer>>;
  createCustomer(hubId: string, input: HubCustomerCreateInput): Promise<HubCustomer>;
  updateCustomer(hubId: string, customerId: string, input: HubCustomerUpdateInput): Promise<HubCustomer>;
  deleteCustomer(hubId: string, customerId: string): Promise<void>;
  previewCustomer(hubId: string, customerId: string): Promise<CustomerPreview>;

  listDeliveries(hubId: string, query: ListQuery, statuses?: HubDeliveryStatus[]): Promise<Page<HubDelivery>>;
  redeliver(deliveryId: string): Promise<void>;

  listOptions(kind: OptionKind, search?: string): Promise<Option[]>;

  listKeys(): Promise<ApiKey[]>;
  /** Returns the full key ONCE. */
  createKey(name: string): Promise<ApiKeyCreated>;
  revokeKey(id: string): Promise<void>;
}

export const hubConnectorService: HubConnectorService = realHubConnectorService;
