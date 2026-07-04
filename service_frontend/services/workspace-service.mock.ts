/**
 * Mock workspace service (Phase A). In-memory dataset + the same query semantics
 * the real backend will expose, so the prototype's list/form behave like prod.
 */
import type { MemberCandidate, Workspace, WorkspaceMember } from '@/types/omnichannel';
import type { ListQuery, ListResult } from '@/types/resource';
import type { WorkspaceService } from './workspace-service';
import { delay, runQuery, type QueryAdapter } from './mock-query';

const DEFAULT_TENANT = 'default';
const EPOCH = Date.parse('2026-06-01T09:00:00Z');
const DAY = 86_400_000;

// Candidate core users (would come from the core users table in Phase B).
const CANDIDATES: MemberCandidate[] = [
  { userId: 'usr-001', name: 'Aaron Tan', email: 'aaron.tan@foundryx.test', status: 'ACTIVE' },
  { userId: 'usr-002', name: 'Bella Lim', email: 'bella.lim@foundryx.test', status: 'ACTIVE' },
  { userId: 'usr-003', name: 'Caleb Wong', email: 'caleb.wong@foundryx.test', status: 'INACTIVE' },
  { userId: 'usr-004', name: 'Dahlia Rahman', email: 'dahlia.rahman@foundryx.test', status: 'ACTIVE' },
  { userId: 'usr-005', name: 'Elias Kaur', email: 'elias.kaur@foundryx.test', status: 'ACTIVE' },
  { userId: 'usr-006', name: 'Farah Singh', email: 'farah.singh@foundryx.test', status: 'ACTIVE' },
  { userId: 'usr-007', name: 'Gavin Lee', email: 'gavin.lee@foundryx.test', status: 'BLOCKED' },
  { userId: 'usr-008', name: 'Hana Chen', email: 'hana.chen@foundryx.test', status: 'ACTIVE' },
];

interface WorkspaceRow extends Workspace {
  memberUserIds: string[];
}

function seed(): WorkspaceRow[] {
  const base: Array<Partial<WorkspaceRow> & { name: string; memberUserIds: string[] }> = [
    { name: 'General', isDefault: true, status: 'ACTIVE', memberUserIds: ['usr-001', 'usr-002', 'usr-003'] },
    { name: 'Sales & Support', isDefault: false, status: 'ACTIVE', memberUserIds: ['usr-004', 'usr-005'] },
    { name: 'Events Concierge', isDefault: false, status: 'ACTIVE', memberUserIds: ['usr-006'] },
    { name: 'Finance Desk', isDefault: false, status: 'INACTIVE', memberUserIds: ['usr-007', 'usr-008'] },
  ];
  return base.map((w, i) => {
    const createdAt = new Date(EPOCH - (i + 1) * DAY * 5).toISOString();
    return {
      id: `wsp-${String(i + 1).padStart(3, '0')}`,
      tenantId: DEFAULT_TENANT,
      name: w.name,
      status: w.status ?? 'ACTIVE',
      isDefault: w.isDefault ?? false,
      channelCount: i === 0 ? 1 : i === 1 ? 1 : 0,
      memberCount: w.memberUserIds.length,
      memberUserIds: w.memberUserIds,
      createdAt,
      updatedAt: createdAt,
      isTrashed: false,
    } satisfies WorkspaceRow;
  });
}

let rows: WorkspaceRow[] = seed();

const adapter: QueryAdapter<WorkspaceRow> = {
  searchFields: ['name'],
  getField: (row, field) => {
    switch (field) {
      case 'created':
        return row.createdAt;
      default:
        return (row as unknown as Record<string, unknown>)[field];
    }
  },
};

function scope(query: ListQuery): WorkspaceRow[] {
  const trashed = query.statusView === 'trashed';
  return rows.filter((r) => r.isTrashed === trashed);
}

function toPublic(r: WorkspaceRow): Workspace {
  const { memberUserIds: _m, ...rest } = r;
  void _m;
  return rest;
}

function csvEscape(v: string): string {
  return /[",\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v;
}
function columnValue(r: WorkspaceRow, colId: string): string {
  switch (colId) {
    case 'name':
      return r.name;
    case 'status':
      return r.status;
    case 'channels':
      return String(r.channelCount);
    case 'members':
      return String(r.memberCount);
    case 'created':
      return r.createdAt;
    default:
      return '';
  }
}

export const mockWorkspaceService: WorkspaceService = {
  async list(query) {
    const scoped = scope(query);
    const res = runQuery(scoped, query, adapter);
    return delay({ ...res, data: res.data.map(toPublic) } as ListResult<Workspace>);
  },

  async get(id) {
    const r = rows.find((w) => w.id === id);
    if (!r) throw new Error('Workspace not found');
    return delay(toPublic(r), 200);
  },

  async getAt(query, index) {
    const scoped = scope(query);
    const full = runQuery(scoped, { ...query, page: 0, pageSize: Math.max(scoped.length, 1) }, adapter);
    const r = full.data[index];
    return delay({ workspace: r ? toPublic(r) : null, total: full.total }, 200);
  },

  async create(input) {
    const now = new Date(EPOCH).toISOString();
    const row: WorkspaceRow = {
      id: `wsp-${String(rows.length + 1).padStart(3, '0')}`,
      tenantId: DEFAULT_TENANT,
      name: input.name,
      status: input.status,
      isDefault: false,
      channelCount: 0,
      memberCount: 0,
      memberUserIds: [],
      createdAt: now,
      updatedAt: now,
      isTrashed: false,
    };
    rows = [row, ...rows];
    return delay(toPublic(row));
  },

  async update(id, input) {
    const idx = rows.findIndex((w) => w.id === id);
    if (idx === -1) throw new Error('Workspace not found');
    const current = rows[idx];
    const updated: WorkspaceRow = {
      ...current,
      name: input.name ?? current.name,
      status: input.status ?? current.status,
      updatedAt: new Date(EPOCH).toISOString(),
    };
    rows[idx] = updated;
    return delay(toPublic(updated));
  },

  async trash(ids) {
    // The default workspace can't be trashed.
    rows = rows.map((r) => (ids.includes(r.id) && !r.isDefault ? { ...r, isTrashed: true } : r));
    return delay(undefined);
  },

  async restore(ids) {
    rows = rows.map((r) => (ids.includes(r.id) ? { ...r, isTrashed: false } : r));
    return delay(undefined);
  },

  async getMembers(workspaceId, search) {
    const r = rows.find((w) => w.id === workspaceId);
    if (!r) return delay([], 200);
    const q = search?.trim().toLowerCase();
    const members: WorkspaceMember[] = r.memberUserIds
      .map((uid, i) => {
        const c = CANDIDATES.find((x) => x.userId === uid);
        return {
          id: `mem-${workspaceId}-${uid}`,
          userId: uid,
          name: c?.name ?? null,
          email: c?.email ?? uid,
          status: c?.status ?? 'ACTIVE',
          assignedAt: new Date(EPOCH - (i + 1) * DAY).toISOString(),
        } satisfies WorkspaceMember;
      })
      .filter((m) => !q || (m.name ?? '').toLowerCase().includes(q) || m.email.toLowerCase().includes(q));
    return delay(members, 200);
  },

  async listAssignable(workspaceId, search) {
    const r = rows.find((w) => w.id === workspaceId);
    const taken = new Set(r?.memberUserIds ?? []);
    const q = search?.trim().toLowerCase();
    const list = CANDIDATES.filter(
      (c) =>
        !taken.has(c.userId) &&
        (!q || (c.name ?? '').toLowerCase().includes(q) || c.email.toLowerCase().includes(q)),
    );
    return delay(list, 150);
  },

  async assignMembers(workspaceId, userIds) {
    const idx = rows.findIndex((w) => w.id === workspaceId);
    if (idx === -1) throw new Error('Workspace not found');
    const set = new Set(rows[idx].memberUserIds);
    userIds.forEach((id) => set.add(id));
    const memberUserIds = Array.from(set);
    rows[idx] = { ...rows[idx], memberUserIds, memberCount: memberUserIds.length };
    return delay(undefined);
  },

  async removeMember(workspaceId, userId) {
    const idx = rows.findIndex((w) => w.id === workspaceId);
    if (idx === -1) throw new Error('Workspace not found');
    const memberUserIds = rows[idx].memberUserIds.filter((id) => id !== userId);
    rows[idx] = { ...rows[idx], memberUserIds, memberCount: memberUserIds.length };
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
