/**
 * Test kit for the Claude connector pages (grants, grant record, products,
 * access, product settings): fixed records, a stand-in for `lib/api-client`
 * that answers reads from them and records every write (method, path,
 * body), and a wrapper that renders a page with the Foundryx UIUX switch on
 * or off. Used by the switch-off parity snapshots and by the tests that
 * compare what both looks send.
 */
import type { ReactNode } from 'react';
import { FX_DEFAULT_THEME } from '@/lib/fx/cookies';
import { FxProvider } from '@/providers/fx-provider';
import { TooltipsProvider } from '@/providers/tooltips-provider';
import type {
  ConnectorActivity,
  ConnectorGrant,
  ConnectorProduct,
  ConnectorProductSettings,
  ConnectorSettingsAuditItem,
  ConnectorTenantSettings,
} from '@/types/connector';

export const T0 = '2026-03-04T05:06:07Z';

export const GRANT: ConnectorGrant = {
  id: 'g-1',
  status: 'active',
  product: 'sorento',
  productName: 'Sorento CRM',
  productUserId: 'crm-user-42',
  userName: 'Jane Doe',
  userEmail: 'jane@example.com',
  clientName: 'Claude',
  grantedAt: T0,
  consentedAt: T0,
  lastUsedAt: T0,
  calls30d: 12,
  revokedReason: null,
};

export const GRANTS: ConnectorGrant[] = [
  GRANT,
  {
    ...GRANT,
    id: 'g-2',
    productUserId: 'crm-user-43',
    userName: 'Lim Wei Jie',
    userEmail: 'wei@example.com',
    lastUsedAt: null,
    calls30d: 0,
  },
];

export const ACTIVITY: ConnectorActivity = {
  calls: [
    {
      id: 'c-1',
      tool: 'list_contacts',
      statusCode: 200,
      rows: 3,
      chars: 120,
      ms: 85,
      truncated: false,
      args: null,
      at: T0,
    },
  ],
  events: [{ id: 'e-1', type: 'granted', at: T0, detail: null }],
};

export const PRODUCT: ConnectorProduct = {
  key: 'sorento',
  displayName: 'Sorento CRM',
  mcpUrl: 'https://ss.example.test/connector/sorento/mcp',
  consentUrl: 'https://crm.example.test/connect/claude',
  apiBase: 'https://crm.example.test/api',
  manifestVersion: '3',
  toolCount: 7,
  fetchedAt: T0,
  stale: false,
  lastError: null,
  secrets: { ssToProduct: 'set', productToSs: 'missing' },
  status: 'ok',
};

export const PRODUCTS: ConnectorProduct[] = [
  PRODUCT,
  {
    ...PRODUCT,
    key: 'ledger',
    displayName: 'Ledger',
    mcpUrl: 'https://ss.example.test/connector/ledger/mcp',
    stale: true,
    lastError: 'timeout',
    secrets: { ssToProduct: 'set', productToSs: 'set' },
  },
];

const v = (value: string | null, source: 'database' | 'environment' | 'default' | 'unset') => ({
  value,
  source,
});

export const PRODUCT_SETTINGS: ConnectorProductSettings = {
  key: 'sorento',
  stored: true,
  status: 'ok',
  fields: {
    displayName: v('Sorento CRM', 'database'),
    connectionId: v('conn-sorento', 'database'),
    consentUrl: v('https://crm.example.test/connect/claude', 'database'),
    apiBaseUrl: v('https://crm.example.test/api', 'environment'),
    issuer: v('sorento', 'default'),
    consentAudience: v('sorento-connector-consent', 'default'),
    callAudience: v('sorento-connector-api', 'default'),
  },
  secrets: {
    ssToProduct: { state: 'set', source: 'database', hint: '****a91c' },
    productToSs: { state: 'missing', source: 'unset', hint: null },
  },
};

export const TENANT: ConnectorTenantSettings = {
  publicBaseUrl: v('https://ss.example.test', 'database'),
  allowedClientCidrs: v('10.0.0.0/8', 'environment'),
  redirectAllowlist: v(null, 'unset'),
  manifestTtlSeconds: v('300', 'default'),
  callTimeoutSeconds: v('30', 'default'),
  callLogRetentionDays: v('90', 'default'),
  ceilings: { callTimeoutSeconds: '120' },
};

export const AUDIT: ConnectorSettingsAuditItem[] = [
  {
    id: 'au-1',
    target: 'product:sorento',
    action: 'updated',
    fields: ['displayName', 'ssToProductSecret'],
    actorUserId: 'me',
    actorName: 'Demo Admin',
    at: T0,
  },
];

export interface RecordedWrite {
  method: string;
  path: string;
  body: unknown;
}

/** Writes seen by the stand-in api client, in order. */
export const writes: RecordedWrite[] = [];

/** Answers a read from the fixtures above. */
function read(path: string): unknown {
  const [p, qs = ''] = path.split('?');
  const q = new URLSearchParams(qs);
  if (p === '/connector/grants') {
    const status = q.get('status') ?? 'active';
    const data = GRANTS.filter((g) => g.status === status);
    if (q.get('page_size') === '1') {
      const i = Number(q.get('page') ?? 0);
      return { data: data.slice(i, i + 1), total: data.length, page: i };
    }
    return { data, total: data.length, page: 0 };
  }
  const grant = GRANTS.find((g) => p === `/connector/grants/${g.id}`);
  if (grant) return grant;
  if (GRANTS.some((g) => p === `/connector/grants/${g.id}/activity`)) return ACTIVITY;
  if (p === '/connector/products') return { data: PRODUCTS };
  if (p === `/connector/products/${PRODUCT_SETTINGS.key}/settings`) return PRODUCT_SETTINGS;
  if (p === '/connector/settings') return TENANT;
  if (p === '/connector/settings/audit') return { data: AUDIT };
  return null;
}

/** What a write answers with. */
function answer(method: string, path: string, body: unknown): unknown {
  const b = (body ?? {}) as Record<string, unknown>;
  if (path.endsWith('/revoke')) return { ok: true };
  if (path === '/connector/grants/bulk-revoke') return { revoked: ((b.ids as string[]) ?? []).length };
  if (path.endsWith('/refresh-manifest')) return PRODUCT;
  if (path === '/connector/products' && method === 'POST') {
    return { ...PRODUCT_SETTINGS, key: String(b.key ?? 'new') };
  }
  if (path.endsWith('/settings') && method === 'PUT' && path.startsWith('/connector/products/')) {
    return PRODUCT_SETTINGS;
  }
  if (path === '/connector/settings' && method === 'PUT') return TENANT;
  if (method === 'DELETE') return { ok: true };
  return null;
}

/** The `apiFetch` stand-in: reads from fixtures, records every write. */
export async function fakeApiFetch(path: string, init: RequestInit = {}): Promise<unknown> {
  const method = (init.method ?? 'GET').toUpperCase();
  if (method === 'GET') return read(path);
  const body = typeof init.body === 'string' ? JSON.parse(init.body) : (init.body ?? null);
  writes.push({ method, path, body });
  return answer(method, path, body);
}

/** Every permission the demo admin holds that these pages read. */
export const ALL_PERMISSIONS = [
  'connector.read',
  'connector.manage',
  'connector.settings',
  'app_store.read',
];

/** Renders `children` with the switch on (`fx`) or off. */
export function Look({ fx, children }: { fx: boolean; children: ReactNode }) {
  return (
    <FxProvider initial={fx} initialTheme={FX_DEFAULT_THEME}>
      <TooltipsProvider>{children}</TooltipsProvider>
    </FxProvider>
  );
}
