/**
 * Mock tenant admin service (Phase A). In-memory tenants with the same query +
 * lifecycle semantics the real backend will expose (plan 07), so the Platform
 * Console behaves like production: slug validation/reservation, platform-tenant
 * protection, suspend/reactivate/archive transitions, provision-with-admin.
 */
import type { ListQuery } from '@/types/resource';
import type {
  TenantDetail,
  TenantLifecycle,
  TenantListItem,
} from '@/types/tenant-admin';
import { isReservedTenantSlug, isValidTenantSlug } from '@/lib/tenant';
import { delay, runQuery, type QueryAdapter } from './mock-query';
import type { TenantAdminService } from './tenant-admin-service';

const EPOCH = Date.parse('2026-06-01T09:00:00Z');
const DAY = 86_400_000;

interface TenantRecord {
  id: string;
  name: string;
  slug: string;
  status: TenantLifecycle;
  isPlatform: boolean;
  contactName: string | null;
  contactEmail: string | null;
  customDomain: string | null;
  notes: string | null;
  userCount: number;
  createdAt: string;
  updatedAt: string;
}

function buildTenants(): TenantRecord[] {
  const mk = (
    i: number,
    partial: Partial<TenantRecord> & Pick<TenantRecord, 'name' | 'slug'>,
  ): TenantRecord => {
    const createdAt = new Date(EPOCH - (i + 1) * DAY * 9).toISOString();
    return {
      id: `tnt-${String(i + 1).padStart(3, '0')}`,
      status: 'ACTIVE',
      isPlatform: false,
      contactName: null,
      contactEmail: null,
      customDomain: null,
      notes: null,
      userCount: 0,
      createdAt,
      updatedAt: createdAt,
      ...partial,
    };
  };

  return [
    mk(0, {
      name: 'Dreamz Platform',
      slug: 'platform',
      isPlatform: true,
      userCount: 3,
    }),
    mk(1, {
      name: 'Dreamz EMS',
      slug: 'default',
      userCount: 12,
      contactName: 'Demo Admin',
      contactEmail: 'demo@example.com',
    }),
    mk(2, {
      name: 'Acme Events',
      slug: 'acme',
      userCount: 24,
      contactName: 'Kay Meister',
      contactEmail: 'kay@acme.test',
      customDomain: 'events.acme.com',
    }),
    mk(3, {
      name: 'Borneo Weddings',
      slug: 'borneo-weddings',
      userCount: 7,
      contactName: 'Aaron Tan',
      contactEmail: 'aaron@borneo.test',
    }),
    mk(4, {
      name: 'Citrus Conferences',
      slug: 'citrus',
      userCount: 15,
      contactName: 'Bella Lim',
      contactEmail: 'bella@citrus.test',
      status: 'SUSPENDED',
      notes: 'Suspended for non-payment 2026-05-20.',
    }),
    mk(5, {
      name: 'Delta Expo',
      slug: 'delta-expo',
      userCount: 4,
      contactName: 'Caleb Wong',
      contactEmail: 'caleb@delta.test',
    }),
    mk(6, {
      name: 'Evergreen Galas',
      slug: 'evergreen',
      userCount: 0,
      status: 'ARCHIVED',
      notes: 'Churned 2026-04.',
    }),
    mk(7, {
      name: 'Festiva Co',
      slug: 'festiva',
      userCount: 9,
      contactName: 'Farah Singh',
      contactEmail: 'farah@festiva.test',
    }),
  ];
}

let tenants: TenantRecord[] = buildTenants();

function toListItem(t: TenantRecord): TenantListItem {
  return {
    id: t.id,
    name: t.name,
    slug: t.slug,
    status: t.status,
    isPlatform: t.isPlatform,
    contactName: t.contactName,
    contactEmail: t.contactEmail,
    customDomain: t.customDomain,
    userCount: t.userCount,
    createdAt: t.createdAt,
    // Mirrors the real wire (sprint-2/02): null = no conditioned edges —
    // populate per row if the mock graph ever gains transitions.
    availableTransitionIds: null,
  };
}

function toDetail(t: TenantRecord): TenantDetail {
  return { ...t };
}

function findOrThrow(id: string): TenantRecord {
  const t = tenants.find((r) => r.id === id);
  if (!t) throw new Error('Tenant not found');
  return t;
}

function touch(t: TenantRecord): void {
  t.updatedAt = new Date(EPOCH).toISOString();
}

function assertNotPlatform(t: TenantRecord): void {
  if (t.isPlatform)
    throw new Error('The platform tenant cannot be suspended or archived.');
}

const adapter: QueryAdapter<TenantRecord> = {
  searchFields: ['name', 'slug', 'contactName', 'contactEmail', 'customDomain'],
  getField: (row, field) => {
    switch (field) {
      case 'tenant':
      case 'name':
        return row.name;
      case 'slug':
        return row.slug;
      case 'status':
        return row.status;
      case 'contact':
      case 'contactEmail':
        return row.contactEmail ?? '';
      case 'contactName':
        return row.contactName ?? '';
      case 'customDomain':
        return row.customDomain ?? '';
      case 'users':
        return row.userCount;
      case 'created':
        return row.createdAt;
      default:
        return (row as unknown as Record<string, unknown>)[field];
    }
  },
};

function columnValue(t: TenantRecord, colId: string): string {
  switch (colId) {
    case 'tenant':
    case 'name':
      return t.name;
    case 'slug':
      return t.slug;
    case 'status':
      return t.status;
    case 'contact':
      return t.contactEmail ?? '';
    case 'users':
      return String(t.userCount);
    case 'created':
      return t.createdAt;
    default:
      return '';
  }
}

function csvEscape(v: string): string {
  return /[",\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v;
}

/** Mirrors the server-side slug guard (plan 07 §4). */
function assertSlugAvailable(slug: string): void {
  if (!isValidTenantSlug(slug)) {
    throw new Error(
      'Slug must be lowercase letters/numbers with single hyphens (3–63 chars).',
    );
  }
  if (isReservedTenantSlug(slug))
    throw new Error(`"${slug}" is a reserved slug.`);
  if (tenants.some((t) => t.slug === slug))
    throw new Error(`Slug "${slug}" is already taken.`);
}

/** Status-view scoping: 'trashed' = archived tenants, 'active' = the rest (plan 07 §4). */
function inView(view: ListQuery['statusView']): TenantRecord[] {
  const archived = view === 'trashed';
  return tenants.filter((t) => (t.status === 'ARCHIVED') === archived);
}

export const mockTenantAdminService: TenantAdminService = {
  async list(query) {
    const result = runQuery(inView(query.statusView), query, adapter);
    return delay({ ...result, data: result.data.map(toListItem) });
  },

  async get(id) {
    return delay(toDetail(findOrThrow(id)), 200);
  },

  async getAt(query, index) {
    const rows = inView(query.statusView);
    const full = runQuery(
      rows,
      { ...query, page: 0, pageSize: Math.max(rows.length, 1) },
      adapter,
    );
    const row = full.data[index];
    return delay(
      { tenant: row ? toDetail(row) : null, total: full.total },
      200,
    );
  },

  async provision(input) {
    assertSlugAvailable(input.slug);
    const now = new Date(EPOCH).toISOString();
    const tenant: TenantRecord = {
      id: `tnt-${String(tenants.length + 1).padStart(3, '0')}`,
      name: input.name,
      slug: input.slug,
      status: 'ACTIVE',
      isPlatform: false,
      contactName: input.contactName ?? null,
      contactEmail: input.contactEmail ?? null,
      customDomain: null,
      notes: input.notes ?? null,
      userCount: 1, // the first admin user (plan 07 §7)
      createdAt: now,
      updatedAt: now,
    };
    tenants = [tenant, ...tenants];
    return delay(toDetail(tenant));
  },

  async update(id, input) {
    const t = findOrThrow(id);
    if (input.name !== undefined) t.name = input.name;
    if (input.contactName !== undefined) t.contactName = input.contactName;
    if (input.contactEmail !== undefined) t.contactEmail = input.contactEmail;
    if (input.customDomain !== undefined) t.customDomain = input.customDomain;
    if (input.notes !== undefined) t.notes = input.notes;
    touch(t);
    return delay(toDetail(t));
  },

  async suspend(id) {
    const t = findOrThrow(id);
    assertNotPlatform(t);
    if (t.status !== 'ACTIVE')
      throw new Error('Only an active tenant can be suspended.');
    t.status = 'SUSPENDED';
    touch(t);
    return delay(toDetail(t));
  },

  async reactivate(id) {
    const t = findOrThrow(id);
    if (t.status === 'ACTIVE') throw new Error('Tenant is already active.');
    t.status = 'ACTIVE';
    touch(t);
    return delay(toDetail(t));
  },

  async archive(id) {
    const t = findOrThrow(id);
    assertNotPlatform(t);
    if (t.status === 'ARCHIVED') throw new Error('Tenant is already archived.');
    t.status = 'ARCHIVED';
    touch(t);
    return delay(toDetail(t));
  },

  async transition(id) {
    // Mock has no edge graph — generic transitions are a no-op echo.
    return delay(toDetail(findOrThrow(id)));
  },

  async statusGraph() {
    // Mock has no engine — empty graph (lifecycle buttons simply absent).
    return delay({
      entityType: 'tenant',
      source: 'platform' as const,
      statuses: [],
      transitions: [],
    });
  },

  async purge(id) {
    const index = tenants.findIndex((t) => t.id === id);
    if (index >= 0) tenants.splice(index, 1);
    await delay(undefined);
  },

  async exportCsv(query, columns, ids) {
    const rows0 = inView(query.statusView);
    const ordered = runQuery(
      rows0,
      { ...query, page: 0, pageSize: Math.max(rows0.length, 1) },
      adapter,
    ).data;
    const rows =
      ids && ids.length ? ordered.filter((t) => ids.includes(t.id)) : ordered;
    const header = columns.map(csvEscape).join(',');
    const body = rows
      .map((t) => columns.map((c) => csvEscape(columnValue(t, c))).join(','))
      .join('\n');
    return delay(`${header}\n${body}`);
  },
};

/** Test helper — reset the in-memory store between specs. */
export function __resetMockTenants(): void {
  tenants = buildTenants();
}
