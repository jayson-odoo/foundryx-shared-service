/**
 * Mock integration service (Phase A). In-memory connections so every list /
 * form state is tunable with no backend running.
 *
 * Failure simulation knobs (for dev + tests):
 *   - password `wrong-password`            → SMTP test fails with an auth error
 *   - secretAccessKey `wrong-secret`       → storage test fails with 403
 *   - host/bucket containing `unreachable` → test fails with a connect timeout
 *   - name `Fail Save`                     → create/update rejects (server error)
 */
import type {
  Connection,
  ConnectionInput,
  IntegrationProvider,
  TestConnectionResult,
} from '@/types/integration';
import type { ListQuery } from '@/types/resource';
import { toCsv } from '@/lib/csv';
import type { IntegrationService } from './integration-service';
import { delay, runQuery, type QueryAdapter } from './mock-query';

const DEFAULT_TENANT = 'default';
const EPOCH = Date.parse('2026-06-01T09:00:00Z');

/**
 * PHASE 1 MOCK (plan 22 S1, AC-22-01/04): the generic SQL-database provider
 * descriptor EXACTLY as the backend `SqlDatabaseProvider.fields()` must emit
 * it (`modules/autocount/sql_provider.py`, provider `sql_database`, type
 * `erp`). The connections form renders it from the registry - zero
 * provider-specific form code. `port.defaultsFrom` drives the per-dialect
 * default (1433 / 5432 / 3306). `password` is Fernet write-only (blank = keep).
 */
export const SQL_DATABASE_PROVIDER: IntegrationProvider = {
  provider: 'sql_database',
  type: 'erp',
  title: 'SQL Database',
  description:
    'Read directly from an accounting database over a read-only login. Microsoft SQL Server, PostgreSQL or MySQL.',
  icon: 'database',
  testLabel: 'Test connection',
  testTarget: null,
  fields: [
    {
      key: 'dbType',
      label: 'Database type',
      type: 'select',
      required: true,
      defaultValue: 'mssql',
      options: [
        { value: 'mssql', label: 'Microsoft SQL Server' },
        { value: 'postgresql', label: 'PostgreSQL' },
        { value: 'mysql', label: 'MySQL' },
      ],
    },
    { key: 'host', label: 'Host', type: 'text', required: true, placeholder: 'db.yourcompany.com' },
    {
      key: 'port',
      label: 'Port',
      type: 'number',
      required: true,
      defaultValue: '1433',
      defaultsFrom: {
        field: 'dbType',
        values: { mssql: '1433', postgresql: '5432', mysql: '3306' },
      },
    },
    { key: 'database', label: 'Database', type: 'text', required: true, placeholder: 'AED_Company_2024' },
    { key: 'username', label: 'Username', type: 'text', required: true, placeholder: 'readonly_user' },
    { key: 'password', label: 'Password', type: 'password', required: true, secret: true },
  ],
};

/** Provider catalog - SMTP (plan 09) + the storage pair (plan 06 D2/D3):
 *  TWO cards, one S3-compatible adapter underneath. R2 derives its endpoint
 *  from the Account ID; the S3 card's optional endpoint covers MinIO/Wasabi. */
const PROVIDERS: IntegrationProvider[] = [
  {
    provider: 'smtp',
    type: 'email',
    title: 'Email (SMTP)',
    description:
      'Send invites, password resets and verifications from your own mail server. Works with any SMTP provider - Gmail, SES, Resend, Mailgun or self-hosted.',
    icon: 'mail',
    testLabel: 'Send test email',
    testTarget: { label: 'Send a test email to', placeholder: 'you@yourcompany.com' },
    fields: [
      { key: 'host', label: 'SMTP host', type: 'text', required: true, placeholder: 'smtp.yourcompany.com' },
      { key: 'port', label: 'Port', type: 'number', required: true, defaultValue: '587' },
      {
        key: 'security',
        label: 'Security',
        type: 'select',
        required: true,
        defaultValue: 'starttls',
        options: [
          { value: 'starttls', label: 'STARTTLS' },
          { value: 'ssl', label: 'SSL/TLS' },
          { value: 'none', label: 'None (not recommended)' },
        ],
      },
      { key: 'username', label: 'Username', type: 'text', required: false, placeholder: 'mailer@yourcompany.com' },
      { key: 'password', label: 'Password', type: 'password', required: false, secret: true },
      { key: 'fromEmail', label: 'From email', type: 'text', required: true, placeholder: 'no-reply@yourcompany.com' },
      { key: 'fromName', label: 'From name', type: 'text', required: false, placeholder: 'Your Company' },
    ],
  },
  {
    provider: 's3',
    type: 'storage',
    title: 'Amazon S3',
    description:
      'Store uploads (avatars, branding, media) in your own S3 bucket. Any S3-compatible service works - AWS, MinIO, Wasabi - via the optional endpoint.',
    icon: 'database',
    testLabel: 'Verify storage',
    testTarget: null,
    fields: [
      { key: 'bucket', label: 'Bucket', type: 'text', required: true, placeholder: 'my-company-assets' },
      { key: 'region', label: 'Region', type: 'text', required: true, placeholder: 'ap-southeast-1' },
      { key: 'accessKeyId', label: 'Access key ID', type: 'password', required: true, secret: true },
      { key: 'secretAccessKey', label: 'Secret access key', type: 'password', required: true, secret: true },
      {
        key: 'cdnBaseUrl',
        label: 'CDN base URL',
        type: 'text',
        required: false,
        placeholder: 'https://cdn.yourcompany.com',
        advanced: true,
      },
      {
        key: 'endpointUrl',
        label: 'Endpoint URL',
        type: 'text',
        required: false,
        placeholder: 'https://s3.amazonaws.com (leave blank for AWS)',
        advanced: true,
      },
    ],
  },
  {
    provider: 'r2',
    type: 'storage',
    title: 'Cloudflare R2',
    description:
      'Store uploads in Cloudflare R2 - S3-compatible, zero egress fees. The endpoint is derived from your Account ID; add a custom domain as the CDN base URL for fast public delivery.',
    icon: 'cloud',
    testLabel: 'Verify storage',
    testTarget: null,
    fields: [
      { key: 'accountId', label: 'Account ID', type: 'text', required: true, placeholder: '23f8c4ed…' },
      { key: 'bucket', label: 'Bucket', type: 'text', required: true, placeholder: 'my-company-assets' },
      { key: 'accessKeyId', label: 'Access key ID', type: 'password', required: true, secret: true },
      { key: 'secretAccessKey', label: 'Secret access key', type: 'password', required: true, secret: true },
      {
        key: 'cdnBaseUrl',
        label: 'CDN base URL',
        type: 'text',
        required: false,
        placeholder: 'https://cdn.yourcompany.com',
        advanced: true,
      },
    ],
  },
  SQL_DATABASE_PROVIDER,
];

let connections: Connection[] = [];
let seq = 0;

/** Test helper - reset the in-memory store between specs. */
export function __resetIntegrationMock(): void {
  connections = [];
  secrets.clear();
  seq = 0;
}

function nowIso(): string {
  return new Date(EPOCH + seq * 60_000).toISOString();
}

function findProvider(provider: string): IntegrationProvider {
  const p = PROVIDERS.find((x) => x.provider === provider);
  if (!p) throw new Error(`Unknown provider "${provider}".`);
  return p;
}

/** Secrets kept off the public Connection shape (write-only contract). */
const secrets = new Map<string, Record<string, string>>();

const adapter: QueryAdapter<Connection> = {
  getField: (row, field) => {
    switch (field) {
      case 'name':
        return row.name;
      case 'provider':
        return row.provider;
      case 'type':
        return row.type;
      case 'status':
        return row.status;
      case 'lastTestedAt':
        return row.lastTestedAt;
      case 'lastError':
        return row.lastError;
      case 'createdAt':
      case 'created':
        return row.createdAt;
      default:
        return (row as unknown as Record<string, unknown>)[field];
    }
  },
  searchFields: ['name', 'provider', 'lastError'],
};

function simulateTest(c: Connection, target?: string): TestConnectionResult {
  const checkedAt = nowIso();
  const stored = secrets.get(c.id) ?? {};
  const probeTarget = `${c.config.host ?? ''}${c.config.bucket ?? ''}`;
  if (probeTarget.includes('unreachable')) {
    return { ok: false, message: `Could not connect to ${probeTarget} (timed out).`, checkedAt };
  }
  if (stored.password === 'wrong-password') {
    return { ok: false, message: 'SMTP authentication failed (535 5.7.8 Bad credentials).', checkedAt };
  }
  if (stored.secretAccessKey === 'wrong-secret') {
    return { ok: false, message: 'Storage authentication failed (403 SignatureDoesNotMatch).', checkedAt };
  }
  if (c.type === 'storage') {
    // Plan 06 D3 - the storage check is a probe-object round-trip, fetched
    // back through the CDN when one is configured.
    return {
      ok: true,
      message: c.config.cdnBaseUrl
        ? `Bucket verified - probe object round-tripped via ${c.config.cdnBaseUrl}.`
        : 'Bucket verified - probe object uploaded, fetched back and deleted.',
      checkedAt,
    };
  }
  return {
    ok: true,
    message: target ? `Test email sent to ${target}.` : 'Connection verified.',
    checkedAt,
  };
}

export const mockIntegrationService: IntegrationService = {
  async providers() {
    return delay([...PROVIDERS]);
  },

  async list(query: ListQuery) {
    const result = runQuery(connections, query, adapter);
    return delay({
      ...result,
      data: result.data.map((c) => ({ ...c, config: { ...c.config } })),
    });
  },

  async get(id: string) {
    const c = connections.find((x) => x.id === id);
    if (!c) throw new Error('Connection not found.');
    return delay({ ...c, config: { ...c.config } });
  },

  async getAt(query: ListQuery, index: number) {
    const all = runQuery(connections, { ...query, page: 0, pageSize: Number.MAX_SAFE_INTEGER }, adapter);
    const row = all.data[index] ?? null;
    return delay({ connection: row ? { ...row, config: { ...row.config } } : null, total: all.total });
  },

  async exportCsv(query: ListQuery, columns: string[], ids?: string[]) {
    const all = runQuery(connections, { ...query, page: 0, pageSize: Number.MAX_SAFE_INTEGER }, adapter);
    const rows = ids?.length ? all.data.filter((c) => ids.includes(c.id)) : all.data;
    const providerTitle = (key: string) =>
      PROVIDERS.find((p) => p.provider === key)?.title ?? key;
    const LABELS: Record<string, string> = {
      name: 'Name',
      provider: 'Provider',
      type: 'Type',
      status: 'Status',
      lastTestedAt: 'Last tested',
      lastError: 'Last error',
      created: 'Created',
    };
    const cell = (c: Connection, col: string): string => {
      switch (col) {
        case 'name':
          return c.name;
        case 'provider':
          return providerTitle(c.provider);
        case 'type':
          return c.type;
        case 'status':
          return c.status;
        case 'lastTestedAt':
          return c.lastTestedAt ?? '';
        case 'lastError':
          return c.lastError ?? '';
        case 'created':
          return c.createdAt;
        default:
          return '';
      }
    };
    return delay(
      toCsv(
        columns.map((col) => LABELS[col] ?? col),
        rows.map((c) => columns.map((col) => cell(c, col))),
      ),
    );
  },

  async create(input: ConnectionInput) {
    const provider = findProvider(input.provider);
    if (input.name === 'Fail Save') throw new Error('The server rejected the connection. Please try again.');
    // ONE active connection per TYPE (plan 06 D7) - resolution must stay
    // deterministic (which bucket does StorageService write to?).
    const sameType = connections.find((c) => c.type === provider.type);
    if (sameType) {
      throw new Error(
        `A ${sameType.type} connection ("${sameType.name}") already exists - disconnect it first.`,
      );
    }
    seq += 1;
    const created: Connection = {
      id: `con-${String(seq).padStart(3, '0')}`,
      tenantId: DEFAULT_TENANT,
      provider: provider.provider,
      type: provider.type,
      name: input.name,
      config: { ...input.config },
      status: 'UNVERIFIED',
      isActive: true,
      lastTestedAt: null,
      lastError: null,
      rateLimitPerMinute: input.rateLimitPerMinute ?? 30,
      createdAt: nowIso(),
      updatedAt: nowIso(),
    };
    secrets.set(created.id, { ...input.credentials });
    connections = [...connections, created];
    return delay({ ...created, config: { ...created.config } });
  },

  async update(id: string, input: Partial<ConnectionInput>) {
    const existing = connections.find((c) => c.id === id);
    if (!existing) throw new Error('Connection not found.');
    if (input.name === 'Fail Save') throw new Error('The server rejected the connection. Please try again.');
    seq += 1;
    const updated: Connection = {
      ...existing,
      name: input.name ?? existing.name,
      config: input.config ? { ...input.config } : existing.config,
      rateLimitPerMinute: input.rateLimitPerMinute ?? existing.rateLimitPerMinute,
      // Config changes invalidate the last verification.
      status: 'UNVERIFIED',
      lastError: null,
      updatedAt: nowIso(),
    };
    // Omitted credential keys keep the stored secret (write-only contract).
    if (input.credentials && Object.keys(input.credentials).length > 0) {
      secrets.set(id, { ...(secrets.get(id) ?? {}), ...input.credentials });
    }
    connections = connections.map((c) => (c.id === id ? updated : c));
    return delay({ ...updated, config: { ...updated.config } });
  },

  async remove(id: string) {
    connections = connections.filter((c) => c.id !== id);
    secrets.delete(id);
    return delay(undefined);
  },

  async activate(id: string) {
    const target = connections.find((c) => c.id === id);
    if (!target) throw new Error('Connection not found.');
    connections = connections.map((c) =>
      c.type === 'storage' ? { ...c, isActive: c.id === id } : c,
    );
    return delay({ ...connections.find((c) => c.id === id)! });
  },

  async test(id: string, target?: string) {
    const c = connections.find((x) => x.id === id);
    if (!c) throw new Error('Connection not found.');
    const result = simulateTest(c, target);
    const settled: Connection = {
      ...c,
      status: result.ok ? 'ACTIVE' : 'ERROR',
      lastTestedAt: result.checkedAt,
      lastError: result.ok ? null : result.message,
    };
    connections = connections.map((x) => (x.id === id ? settled : x));
    // A touch slower than list calls - a real handshake takes a moment.
    return delay(result, 700);
  },
};
