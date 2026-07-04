/**
 * Mock role service (Phase A). In-memory roles + permission grants + user
 * assignments, with the same query semantics the real backend exposes, so the
 * Roles list/form behave like production. Counts (users, permissions) are
 * computed on read — never stored (plan 03 §6).
 */
import type { AssignableUser, RoleDetail, RoleListItem, RoleUser } from '@/types/role';
import type { UserStatus } from '@/types/user';
import type { RoleService } from './role-service';
import { applyImpliedRead } from '@/lib/permissions';
import { ALL_PERMISSION_KEYS } from './permission-service.mock';
import { delay, runQuery, type QueryAdapter } from './mock-query';

const DEFAULT_TENANT = 'default';
const EPOCH = Date.parse('2026-06-01T09:00:00Z');
const DAY = 86_400_000;

/** Internal storage shape (counts are derived, not stored). */
interface RoleRecord {
  id: string;
  name: string;
  description: string | null;
  isSystem: boolean;
  permissionKeys: string[];
  createdAt: string;
}

interface PoolUser {
  id: string;
  name: string;
  email: string;
  status: UserStatus;
}

// A small tenant user pool for assignment.
const POOL: PoolUser[] = [
  { id: 'usr-001', name: 'Kay Meister', email: 'kaymeister@globats.com', status: 'ACTIVE' },
  { id: 'usr-002', name: 'MCF User', email: 'mcfuser@sorento.com.my', status: 'ACTIVE' },
  { id: 'usr-003', name: 'Aaron Tan', email: 'aaron.tan@foundryx.test', status: 'ACTIVE' },
  { id: 'usr-004', name: 'Bella Lim', email: 'bella.lim@foundryx.test', status: 'INACTIVE' },
  { id: 'usr-005', name: 'Caleb Wong', email: 'caleb.wong@foundryx.test', status: 'ACTIVE' },
  { id: 'usr-006', name: 'Dahlia Rahman', email: 'dahlia.rahman@foundryx.test', status: 'BLOCKED' },
  { id: 'usr-007', name: 'Elias Kaur', email: 'elias.kaur@foundryx.test', status: 'ACTIVE' },
  { id: 'usr-008', name: 'Farah Singh', email: 'farah.singh@foundryx.test', status: 'INVITED' },
  { id: 'usr-009', name: 'Gavin Lee', email: 'gavin.lee@foundryx.test', status: 'ACTIVE' },
  { id: 'usr-010', name: 'Hana Chen', email: 'hana.chen@foundryx.test', status: 'ACTIVE' },
];

const crud = (r: string) => [`${r}.read`, `${r}.create`, `${r}.update`, `${r}.delete`];

function buildRoles(): RoleRecord[] {
  const mk = (
    i: number,
    name: string,
    description: string,
    permissionKeys: string[],
  ): RoleRecord => ({
    id: `role-${String(i + 1).padStart(3, '0')}`,
    name,
    description,
    isSystem: true, // all seeded roles are system (plan 03 §5)
    permissionKeys: applyImpliedRead(permissionKeys),
    createdAt: new Date(EPOCH - (i + 1) * DAY * 5).toISOString(),
  });

  return [
    mk(0, 'Admin', 'Full system access with all permissions', ALL_PERMISSION_KEYS),
    mk(1, 'Marketing Executive', 'Access to marketing tools and campaign management', [
      'dashboard.read',
      ...crud('events'),
      'reports.read',
      'reports.export',
    ]),
    mk(2, 'Customer Service', 'Handle customer queries and support tickets', [
      'dashboard.read',
      'orders.read',
      'orders.update',
      'users.read',
    ]),
    mk(3, 'Technical Executive', 'Technical operations and infrastructure management', [
      'dashboard.read',
      ...crud('inventory'),
      ...crud('products'),
      'settings.read',
    ]),
    mk(4, 'Finance', 'Manage billing, invoicing and financial reports', [
      'dashboard.read',
      ...crud('finance'),
      'reports.read',
      'orders.approve',
    ]),
    mk(5, 'HR Manager', 'Human resources, onboarding and team management', [
      'dashboard.read',
      ...crud('users'),
    ]),
    mk(6, 'Viewer', 'Read-only access to dashboards and reports', [
      'dashboard.read',
      'reports.read',
    ]),
  ];
}

let roles: RoleRecord[] = buildRoles();

// roleId -> { userId -> assignedAt ISO }
const assignments = new Map<string, Map<string, string>>();
function seedAssignments() {
  const set = (roleId: string, pairs: [string, number][]) => {
    const m = new Map<string, string>();
    for (const [uid, dayOffset] of pairs) m.set(uid, new Date(EPOCH - dayOffset * DAY).toISOString());
    assignments.set(roleId, m);
  };
  set('role-001', [['usr-001', 10], ['usr-002', 7]]); // Admin → Kay, MCF (matches image)
  set('role-002', [['usr-003', 5]]);
  set('role-003', [['usr-004', 4], ['usr-005', 3], ['usr-007', 2]]);
  set('role-004', [['usr-009', 6], ['usr-010', 1], ['usr-005', 8]]);
}
seedAssignments();

function userCount(roleId: string): number {
  return assignments.get(roleId)?.size ?? 0;
}

function toListItem(r: RoleRecord): RoleListItem {
  return {
    id: r.id,
    name: r.name,
    description: r.description,
    isSystem: r.isSystem,
    userCount: userCount(r.id),
    permissionCount: r.permissionKeys.length,
    createdAt: r.createdAt,
  };
}

function toDetail(r: RoleRecord): RoleDetail {
  return { ...toListItem(r), permissionKeys: [...r.permissionKeys] };
}

/** Assigned users' names + emails for a role (search corpus). */
function assignedUserTokens(roleId: string): string[] {
  const m = assignments.get(roleId);
  if (!m) return [];
  return Array.from(m.keys()).flatMap((uid) => {
    const u = POOL.find((p) => p.id === uid);
    return u ? [u.name, u.email] : [];
  });
}

const adapter: QueryAdapter<RoleRecord> = {
  // Search matches the role itself, its assigned users, and its permission keys.
  searchFields: ['name', 'description', 'assignedUsers', 'permissionKeys'],
  getField: (row, field) => {
    switch (field) {
      case 'role':
      case 'name':
        return row.name;
      case 'description':
        return row.description ?? '';
      case 'users':
        return userCount(row.id);
      case 'permissions':
        return row.permissionKeys.length;
      case 'permissionKeys':
        return row.permissionKeys;
      case 'assignedUsers':
        return assignedUserTokens(row.id);
      case 'created':
        return row.createdAt;
      case 'system':
        return row.isSystem;
      default:
        return (row as unknown as Record<string, unknown>)[field];
    }
  },
};

function columnValue(r: RoleRecord, colId: string): string {
  switch (colId) {
    case 'role':
    case 'name':
      return r.name;
    case 'description':
      return r.description ?? '';
    case 'users':
      return String(userCount(r.id));
    case 'permissions':
      return String(r.permissionKeys.length);
    case 'created':
      return r.createdAt;
    default:
      return '';
  }
}

function csvEscape(v: string): string {
  return /[",\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v;
}

function poolToAssignable(u: PoolUser): AssignableUser {
  return { id: u.id, name: u.name, email: u.email, avatar: null, status: u.status };
}

export const mockRoleService: RoleService = {
  async list(query) {
    const result = runQuery(roles, query, adapter);
    return delay({ ...result, data: result.data.map(toListItem) });
  },

  async get(id) {
    const role = roles.find((r) => r.id === id);
    if (!role) throw new Error('Role not found');
    return delay(toDetail(role), 200);
  },

  async getAt(query, index) {
    const full = runQuery(roles, { ...query, page: 0, pageSize: Math.max(roles.length, 1) }, adapter);
    const row = full.data[index];
    return delay({ role: row ? toDetail(row) : null, total: full.total }, 200);
  },

  async create(input) {
    const role: RoleRecord = {
      id: `role-${String(roles.length + 1).padStart(3, '0')}`,
      name: input.name,
      description: input.description ?? null,
      isSystem: input.isSystem ?? false, // user-created roles default deletable
      permissionKeys: applyImpliedRead(input.permissionKeys),
      createdAt: new Date(EPOCH).toISOString(),
    };
    roles = [role, ...roles];
    assignments.set(role.id, new Map());
    return delay(toDetail(role));
  },

  async update(id, input) {
    const idx = roles.findIndex((r) => r.id === id);
    if (idx === -1) throw new Error('Role not found');
    const current = roles[idx];
    const updated: RoleRecord = {
      ...current,
      name: input.name ?? current.name,
      description: input.description !== undefined ? input.description : current.description,
      isSystem: input.isSystem ?? current.isSystem,
      permissionKeys: input.permissionKeys
        ? applyImpliedRead(input.permissionKeys)
        : current.permissionKeys,
    };
    roles[idx] = updated;
    return delay(toDetail(updated));
  },

  async remove(id) {
    const role = roles.find((r) => r.id === id);
    if (!role) throw new Error('Role not found');
    if (role.isSystem) throw new Error('System roles cannot be deleted.');
    roles = roles.filter((r) => r.id !== id);
    assignments.delete(id);
    return delay(undefined);
  },

  async getAssignedUsers(roleId, search) {
    const m = assignments.get(roleId) ?? new Map<string, string>();
    const q = search?.trim().toLowerCase();
    const rows: RoleUser[] = Array.from(m.entries())
      .map(([uid, assignedAt]) => {
        const u = POOL.find((p) => p.id === uid)!;
        return { id: u.id, name: u.name, email: u.email, avatar: null, status: u.status, assignedAt };
      })
      .filter((u) => !q || u.name.toLowerCase().includes(q) || u.email.toLowerCase().includes(q))
      .sort((a, b) => (a.assignedAt < b.assignedAt ? 1 : -1));
    return delay(rows, 200);
  },

  async listAssignable(roleId, search) {
    const m = assignments.get(roleId) ?? new Map<string, string>();
    const q = search?.trim().toLowerCase();
    const rows = POOL.filter((u) => !m.has(u.id))
      .filter((u) => !q || u.name.toLowerCase().includes(q) || u.email.toLowerCase().includes(q))
      .map(poolToAssignable);
    return delay(rows, 150);
  },

  async assignUsers(roleId, userIds) {
    const m = assignments.get(roleId) ?? new Map<string, string>();
    const now = new Date(EPOCH).toISOString();
    for (const uid of userIds) if (!m.has(uid)) m.set(uid, now);
    assignments.set(roleId, m);
    return delay(undefined);
  },

  async removeUser(roleId, userId) {
    assignments.get(roleId)?.delete(userId);
    return delay(undefined);
  },

  async exportCsv(query, columns, ids) {
    const ordered = runQuery(roles, { ...query, page: 0, pageSize: Math.max(roles.length, 1) }, adapter).data;
    const rows = ids && ids.length ? ordered.filter((r) => ids.includes(r.id)) : ordered;
    const header = columns.map(csvEscape).join(',');
    const body = rows.map((r) => columns.map((c) => csvEscape(columnValue(r, c))).join(',')).join('\n');
    return delay(`${header}\n${body}`);
  },
};

// Re-exported for tests / Phase-B parity checks.
export { DEFAULT_TENANT };
