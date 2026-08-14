/**
 * Mock App Store service (Phase A). In-memory per-tenant install state with the
 * same lifecycle semantics the real backend will enforce (plan 08 §5), so the
 * storefront exercises every card state with no backend: not installed, active,
 * inactive, update available - plus typed-confirm uninstall and per-tenant
 * isolation for the console Modules tab.
 */
import type { ModuleStatus, StoreAction, StoreModule } from '@/types/app-store';
import type { AppStoreService } from './app-store-service';
import { delay } from './mock-query';

const EPOCH = Date.parse('2026-06-01T09:00:00Z');
const DAY = 86_400_000;

/** Global catalog row (mirrors the `modules` table, synced from manifests). */
interface CatalogEntry {
  name: string;
  title: string;
  description: string;
  icon: string | null;
  version: string; // current code version
}

/** Per-tenant install row (mirrors `tenant_modules`). */
interface InstallRecord {
  status: ModuleStatus;
  installedVersion: string;
  installedAt: string;
}

const CATALOG: CatalogEntry[] = [
  {
    name: 'omnichannel',
    title: 'Omnichannel',
    description:
      'WhatsApp Business messaging - connect numbers via Meta Embedded Signup, manage workspaces and channels.',
    icon: 'message-square',
    version: '0.1.0',
  },
  {
    name: 'helpdesk',
    title: 'Helpdesk',
    description: 'Ticketing for attendee support - queues, SLAs and canned replies.',
    icon: 'life-buoy',
    version: '1.1.0',
  },
  {
    name: 'commercial',
    title: 'Commercial',
    description: 'Quotations, invoicing and payment tracking for event projects.',
    icon: 'receipt-text',
    version: '1.0.0',
  },
  {
    name: 'forms',
    title: 'Forms',
    description: 'Registration and survey form builder with public share links.',
    icon: 'clipboard-list',
    version: '1.0.0',
  },
];

/** Key for the acting admin's own tenant (the storefront path). */
const SELF = '__self__';

function seedTenantState(): Map<string, InstallRecord> {
  const at = (d: number) => new Date(EPOCH - d * DAY).toISOString();
  return new Map<string, InstallRecord>([
    // Matches reality post-backfill: omnichannel active at the current version.
    ['omnichannel', { status: 'ACTIVE', installedVersion: '0.1.0', installedAt: at(30) }],
    // Update available: provisioned at 1.0.0, code moved to 1.1.0.
    ['helpdesk', { status: 'ACTIVE', installedVersion: '1.0.0', installedAt: at(20) }],
    // Deactivated - data kept, routes 403, menu hidden.
    ['forms', { status: 'INACTIVE', installedVersion: '1.0.0', installedAt: at(10) }],
    // 'commercial' absent = not installed.
  ]);
}

function buildInstalls(): Map<string, Map<string, InstallRecord>> {
  return new Map([
    [SELF, seedTenantState()],
    ['tnt-002', seedTenantState()],
    [
      'tnt-003',
      new Map([
        [
          'omnichannel',
          {
            status: 'ACTIVE' as ModuleStatus,
            installedVersion: '0.1.0',
            installedAt: new Date(EPOCH - 5 * DAY).toISOString(),
          },
        ],
      ]),
    ],
  ]);
}

/** tenantKey → moduleName → install row. Operator view sees other tenants' maps. */
let installs = buildInstalls();

function tenantMap(key: string): Map<string, InstallRecord> {
  let m = installs.get(key);
  if (!m) {
    m = new Map();
    installs.set(key, m);
  }
  return m;
}

function catalogOrThrow(name: string): CatalogEntry {
  const entry = CATALOG.find((c) => c.name === name);
  if (!entry) throw new Error('Module not found');
  return entry;
}

function toStoreModule(entry: CatalogEntry, rec: InstallRecord | undefined): StoreModule {
  return {
    name: entry.name,
    title: entry.title,
    description: entry.description,
    icon: entry.icon,
    version: entry.version,
    status: rec?.status ?? null,
    installedVersion: rec?.installedVersion ?? null,
    updateAvailable: rec ? rec.installedVersion !== entry.version : false,
    installedAt: rec?.installedAt ?? null,
  };
}

function listFor(key: string): StoreModule[] {
  const m = tenantMap(key);
  return CATALOG.map((entry) => toStoreModule(entry, m.get(entry.name)));
}

/** Mirrors the server-side transition guards (plan 08 §5). */
function actFor(key: string, name: string, action: StoreAction): StoreModule {
  const entry = catalogOrThrow(name);
  const m = tenantMap(key);
  const rec = m.get(name);

  switch (action) {
    case 'install': {
      if (rec) throw new Error(`${entry.title} is already installed.`);
      m.set(name, {
        status: 'ACTIVE',
        installedVersion: entry.version,
        installedAt: new Date(EPOCH).toISOString(),
      });
      break;
    }
    case 'deactivate': {
      if (!rec || rec.status !== 'ACTIVE')
        throw new Error(`Only an active module can be deactivated.`);
      rec.status = 'INACTIVE';
      break;
    }
    case 'reactivate': {
      if (!rec || rec.status !== 'INACTIVE')
        throw new Error(`Only an inactive module can be reactivated.`);
      rec.status = 'ACTIVE';
      break;
    }
    case 'update': {
      if (!rec) throw new Error(`${entry.title} is not installed.`);
      if (rec.installedVersion === entry.version)
        throw new Error(`${entry.title} is already up to date.`);
      rec.installedVersion = entry.version;
      break;
    }
  }
  return toStoreModule(entry, m.get(name));
}

function uninstallFor(key: string, name: string, confirmName: string): void {
  const entry = catalogOrThrow(name);
  const m = tenantMap(key);
  if (!m.get(name)) throw new Error(`${entry.title} is not installed.`);
  // Typed confirmation - the backend enforces the same equality (plan 08 §7).
  if (confirmName !== name) throw new Error('Confirmation name does not match the module name.');
  m.delete(name);
}

export const mockAppStoreService: AppStoreService = {
  async catalog() {
    return delay(listFor(SELF));
  },

  async installed() {
    const m = tenantMap(SELF);
    return delay(
      Array.from(m.entries()).map(([module, rec]) => ({
        module,
        status: rec.status,
        version: rec.installedVersion,
      })),
      150,
    );
  },

  async act(name, action) {
    return delay(actFor(SELF, name, action));
  },

  async uninstall(name, confirmName) {
    uninstallFor(SELF, name, confirmName);
    return delay(undefined);
  },

  async catalogForTenant(tenantId) {
    return delay(listFor(tenantId));
  },

  async actForTenant(tenantId, name, action) {
    return delay(actFor(tenantId, name, action));
  },

  async uninstallForTenant(tenantId, name, confirmName) {
    uninstallFor(tenantId, name, confirmName);
    return delay(undefined);
  },
};

/** Test helper - reset the in-memory store between specs. */
export function __resetMockAppStore(): void {
  installs = buildInstalls();
}
