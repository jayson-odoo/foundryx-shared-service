/**
 * Mock channel service (Phase A). In-memory dataset shared with the onboarding
 * mock (so a freshly "connected" channel appears in the list immediately).
 */
import type {
  Channel,
  ChannelProfile,
  EmbeddedSignupResult,
  UpdateChannelProfileInput,
} from '@/types/omnichannel';
import type { ListQuery, ListResult } from '@/types/resource';
import { WHATSAPP_VERTICAL_SET } from '@/lib/whatsapp-verticals';
import type { ChannelService, TestConnectionResult } from './channel-service';
import { delay, runQuery, type QueryAdapter } from './mock-query';

const DEFAULT_TENANT = 'default';
const EPOCH = Date.parse('2026-06-01T09:00:00Z');
const DAY = 86_400_000;

type ChannelRow = Channel;

function seed(): ChannelRow[] {
  const base: Array<
    Pick<Channel, 'name' | 'workspaceId' | 'workspaceName' | 'status' | 'isActive' | 'displayPhoneNumber'>
  > = [
    { name: 'Dreamz Official WhatsApp', workspaceId: 'wsp-001', workspaceName: 'General', status: 'ACTIVE', isActive: true, displayPhoneNumber: '+65 8123 4567' },
    { name: 'Sales WhatsApp', workspaceId: 'wsp-002', workspaceName: 'Sales & Support', status: 'ACTIVE', isActive: true, displayPhoneNumber: '+65 8222 9090' },
  ];
  return base.map((c, i) => {
    const createdAt = new Date(EPOCH - (i + 1) * DAY * 4).toISOString();
    return {
      id: `chn-${String(i + 1).padStart(3, '0')}`,
      tenantId: DEFAULT_TENANT,
      workspaceId: c.workspaceId,
      workspaceName: c.workspaceName,
      channelType: 'WHATSAPP',
      name: c.name,
      status: c.status,
      isActive: c.isActive,
      wabaId: `waba-${100 + i}`,
      phoneNumberId: `pn-${200 + i}`,
      displayPhoneNumber: c.displayPhoneNumber,
      businessAccountName: c.name,
      verifiedName: c.name,
      lastVerifiedAt: createdAt,
      profileSyncedAt: null,
      createdAt,
      updatedAt: createdAt,
      isTrashed: false,
    } satisfies ChannelRow;
  });
}

/** Workspace names by id — mirrors the workspace mock seed (for display only). */
const WORKSPACE_NAMES: Record<string, string> = {
  'wsp-001': 'General',
  'wsp-002': 'Sales & Support',
  'wsp-003': 'Events Concierge',
  'wsp-004': 'Finance Desk',
};

let rows: ChannelRow[] = seed();

/** Per-channel mirrored profile (mock). Empty until Sync Profile is run. */
const profiles: Record<string, ChannelProfile> = {};
function emptyProfile(): ChannelProfile {
  return {
    about: null,
    address: null,
    description: null,
    email: null,
    vertical: null,
    website1: null,
    website2: null,
    profilePictureUrl: null,
    profileSyncedAt: null,
  };
}

const adapter: QueryAdapter<ChannelRow> = {
  searchFields: ['name', 'displayPhoneNumber'],
  getField: (row, field) => {
    switch (field) {
      case 'created':
        return row.createdAt;
      default:
        return (row as unknown as Record<string, unknown>)[field];
    }
  },
};

function scope(query: ListQuery): ChannelRow[] {
  const trashed = query.statusView === 'trashed';
  return rows.filter((r) => r.isTrashed === trashed);
}
function toPublic(r: ChannelRow): Channel {
  return r;
}
function csvEscape(v: string): string {
  return /[",\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v;
}
function columnValue(r: ChannelRow, colId: string): string {
  switch (colId) {
    case 'name':
      return r.name;
    case 'channelType':
      return r.channelType;
    case 'phone':
      return r.displayPhoneNumber ?? '';
    case 'status':
      return r.status;
    case 'created':
      return r.createdAt;
    default:
      return '';
  }
}

/**
 * Internal hook for the onboarding mock: provision a channel from an Embedded
 * Signup result so it shows up in the channels list (mirrors the backend
 * auto-provision step). Phase A only.
 */
export function __mockProvisionChannel(workspaceId: string, result: EmbeddedSignupResult): Channel {
  const now = new Date(EPOCH).toISOString();
  const row: ChannelRow = {
    id: `chn-${String(rows.length + 1).padStart(3, '0')}`,
    tenantId: DEFAULT_TENANT,
    workspaceId,
    workspaceName: WORKSPACE_NAMES[workspaceId] ?? 'Workspace',
    channelType: 'WHATSAPP',
    name: result.businessName ?? 'WhatsApp',
    status: 'ACTIVE',
    isActive: true,
    wabaId: result.wabaId,
    phoneNumberId: result.phoneNumberId,
    displayPhoneNumber: result.displayPhoneNumber ?? null,
    businessAccountName: result.businessName ?? null,
    verifiedName: result.businessName ?? null,
    lastVerifiedAt: now,
    profileSyncedAt: null,
    createdAt: now,
    updatedAt: now,
    isTrashed: false,
  };
  rows = [row, ...rows];
  return toPublic(row);
}

export const mockChannelService: ChannelService = {
  async list(query) {
    const scoped = scope(query);
    const res = runQuery(scoped, query, adapter);
    return delay({ ...res, data: res.data.map(toPublic) } as ListResult<Channel>);
  },

  async get(id) {
    const r = rows.find((c) => c.id === id);
    if (!r) throw new Error('Channel not found');
    return delay(toPublic(r), 200);
  },

  async getAt(query, index) {
    const scoped = scope(query);
    const full = runQuery(scoped, { ...query, page: 0, pageSize: Math.max(scoped.length, 1) }, adapter);
    const r = full.data[index];
    return delay({ channel: r ? toPublic(r) : null, total: full.total }, 200);
  },

  async listByWorkspace(workspaceId) {
    const list = rows.filter((c) => c.workspaceId === workspaceId && !c.isTrashed).map(toPublic);
    return delay(list, 200);
  },

  async update(id, input) {
    const idx = rows.findIndex((c) => c.id === id);
    if (idx === -1) throw new Error('Channel not found');
    const current = rows[idx];
    const updated: ChannelRow = {
      ...current,
      name: input.name ?? current.name,
      isActive: input.isActive ?? current.isActive,
      status: input.isActive === false ? 'INACTIVE' : input.isActive === true ? 'ACTIVE' : current.status,
      updatedAt: new Date(EPOCH).toISOString(),
    };
    rows[idx] = updated;
    return delay(toPublic(updated));
  },

  async testConnection(id) {
    const r = rows.find((c) => c.id === id);
    if (!r) throw new Error('Channel not found');
    r.lastVerifiedAt = new Date(EPOCH).toISOString();
    return delay<TestConnectionResult>({
      ok: true,
      message: `Reached ${r.displayPhoneNumber ?? 'number'} successfully.`,
      checkedAt: r.lastVerifiedAt,
    });
  },

  async syncConfig(id) {
    const r = rows.find((c) => c.id === id);
    if (!r) throw new Error('Channel not found');
    r.businessAccountName = 'Dreamz Events (dev sandbox)';
    r.verifiedName = r.verifiedName ?? r.name;
    r.lastVerifiedAt = new Date(EPOCH).toISOString();
    return delay(toPublic(r));
  },

  async getProfile(id) {
    if (!rows.find((c) => c.id === id)) throw new Error('Channel not found');
    return delay(profiles[id] ?? emptyProfile());
  },

  async syncProfile(id) {
    if (!rows.find((c) => c.id === id)) throw new Error('Channel not found');
    const synced: ChannelProfile = {
      about: 'Premier event spaces & concierge in KL.',
      address: 'Level 12, Menara Dreamz, Kuala Lumpur',
      description: 'We host weddings, conferences and galas.',
      email: 'hello@dreamz.example',
      vertical: 'EVENT_PLAN',
      website1: 'https://dreamz.example',
      website2: null,
      profilePictureUrl: null,
      profileSyncedAt: new Date(EPOCH).toISOString(),
    };
    profiles[id] = synced;
    return delay(synced);
  },

  async saveProfile(id, input: UpdateChannelProfileInput) {
    if (!rows.find((c) => c.id === id)) throw new Error('Channel not found');
    if (input.vertical != null && !WHATSAPP_VERTICAL_SET.has(input.vertical)) {
      throw new Error('Not a valid WhatsApp business vertical.');
    }
    const current = profiles[id] ?? emptyProfile();
    const next: ChannelProfile = {
      ...current,
      about: input.about !== undefined ? input.about : current.about,
      address: input.address !== undefined ? input.address : current.address,
      description: input.description !== undefined ? input.description : current.description,
      email: input.email !== undefined ? input.email : current.email,
      vertical: input.vertical !== undefined ? input.vertical : current.vertical,
      website1: input.website1 !== undefined ? input.website1 : current.website1,
      website2: input.website2 !== undefined ? input.website2 : current.website2,
    };
    profiles[id] = next;
    return delay(next);
  },

  async disconnect(ids) {
    rows = rows.map((r) => (ids.includes(r.id) ? { ...r, isTrashed: true, isActive: false, status: 'INACTIVE' } : r));
    return delay(undefined);
  },

  async restore(ids) {
    rows = rows.map((r) =>
      ids.includes(r.id) ? { ...r, isTrashed: false, isActive: true, status: 'ACTIVE' } : r,
    );
    return delay(undefined);
  },

  async remove(ids) {
    rows = rows.filter((r) => !ids.includes(r.id));
    return delay(undefined);
  },

  async exportCsv(query, columns, ids) {
    const scoped = scope(query);
    const ordered = runQuery(scoped, { ...query, page: 0, pageSize: Math.max(scoped.length, 1) }, adapter).data;
    const picked = ids && ids.length ? ordered.filter((r) => ids.includes(r.id)) : ordered;
    const header = columns.map(csvEscape).join(',');
    const body = picked.map((r) => columns.map((c) => csvEscape(columnValue(r, c))).join(',')).join('\n');
    return delay(`${header}\n${body}`);
  },
};
