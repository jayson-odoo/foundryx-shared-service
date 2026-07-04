/**
 * Mock user service (Phase A). In-memory dataset + the same query semantics the
 * real backend will expose, so the prototype's list/form behave like production.
 */
import type { Role, User, UserStatus } from '@/types/user';
import type { ListQuery, ListResult } from '@/types/resource';
import type { UserService } from './user-service';
import { MOCK_ROLES } from './roles-service';
import { delay, runQuery, type QueryAdapter } from './mock-query';

const DEFAULT_TENANT = 'default';

const FIRST = [
  'Aaron', 'Bella', 'Caleb', 'Dahlia', 'Elias', 'Farah', 'Gavin', 'Hana', 'Idris', 'Jules',
  'Kira', 'Liam', 'Mira', 'Noah', 'Omar', 'Priya', 'Quinn', 'Rania', 'Sami', 'Tara',
  'Umar', 'Vera', 'Wes', 'Xena', 'Yara', 'Zane', 'Ada', 'Bilal', 'Cora', 'Dean',
  'Esha', 'Finn', 'Gita', 'Hugo', 'Ivy', 'Jad', 'Kay', 'Lena', 'Marc', 'Nadia',
  'Owen', 'Pia', 'Rhys',
];
const LAST = [
  'Tan', 'Lim', 'Wong', 'Rahman', 'Kaur', 'Singh', 'Lee', 'Chen', 'Patel', 'Khan',
  'Ng', 'Ho', 'Goh', 'Devi', 'Yusof', 'Ali', 'Ong', 'Teo', 'Raj', 'Sim',
];

function roleSet(i: number): Role[] {
  // Deterministic spread: most users 1 role, some 2, a few none.
  if (i % 7 === 0) return [];
  if (i % 5 === 0) return [MOCK_ROLES[i % MOCK_ROLES.length], MOCK_ROLES[(i + 2) % MOCK_ROLES.length]];
  return [MOCK_ROLES[i % MOCK_ROLES.length]];
}

function statusFor(i: number): UserStatus {
  if (i % 11 === 0) return 'BLOCKED';
  if (i % 6 === 0) return 'INVITED';
  if (i % 4 === 0) return 'INACTIVE';
  return 'ACTIVE';
}

// Fixed epoch so dates are deterministic (no Date.now()) across reloads/tests.
const EPOCH = Date.parse('2026-06-01T09:00:00Z');
const DAY = 86_400_000;

function buildSeed(): User[] {
  return Array.from({ length: 43 }, (_, i) => {
    const first = FIRST[i % FIRST.length];
    const last = LAST[i % LAST.length];
    const name = `${first} ${last}`;
    const status = statusFor(i);
    const createdAt = new Date(EPOCH - (i + 1) * DAY * 3).toISOString();
    const signedIn = i % 3 !== 0 && status !== 'INVITED';
    return {
      id: `usr-${String(i + 1).padStart(3, '0')}`,
      tenantId: DEFAULT_TENANT,
      name,
      email: `${first.toLowerCase()}.${last.toLowerCase()}@foundryx.test`,
      status,
      avatar: null,
      roles: roleSet(i),
      createdAt,
      lastSignInAt: signedIn ? new Date(EPOCH - (i + 1) * DAY).toISOString() : null,
      emailVerifiedAt: status === 'INVITED' ? null : createdAt,
      isTrashed: i % 13 === 0 && i !== 0, // a handful trashed for the Trashed view
    } satisfies User;
  });
}

// Module-level mutable store (Phase A only).
let users: User[] = buildSeed();

const adapter: QueryAdapter<User> = {
  searchFields: ['name', 'email'],
  getField: (row, field) => {
    switch (field) {
      case 'user':
        return row.name;
      case 'role':
        return row.roles.map((r) => r.name);
      case 'joined':
        return row.createdAt;
      case 'lastSignIn':
        return row.lastSignInAt;
      default:
        return (row as unknown as Record<string, unknown>)[field];
    }
  },
};

function scopeByStatusView(query: ListQuery): User[] {
  const trashed = query.statusView === 'trashed';
  return users.filter((u) => u.isTrashed === trashed);
}

function columnValue(u: User, colId: string): string {
  switch (colId) {
    case 'user':
    case 'name':
      return u.name ?? '';
    case 'email':
      return u.email;
    case 'role':
      return u.roles.map((r) => r.name).join('; ');
    case 'status':
      return u.status;
    case 'joined':
      return u.createdAt;
    case 'lastSignIn':
      return u.lastSignInAt ?? '';
    default:
      return '';
  }
}

function csvEscape(v: string): string {
  return /[",\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v;
}

export const mockUserService: UserService = {
  async list(query) {
    const scoped = scopeByStatusView(query);
    return delay(runQuery(scoped, query, adapter));
  },

  async get(id) {
    const user = users.find((u) => u.id === id);
    if (!user) throw new Error('User not found');
    return delay(user, 200);
  },

  async getAt(query, index) {
    const scoped = scopeByStatusView(query);
    const full: ListResult<User> = runQuery(
      scoped,
      { ...query, page: 0, pageSize: Math.max(scoped.length, 1) },
      adapter,
    );
    return delay({ user: full.data[index] ?? null, total: full.total }, 200);
  },

  async create(input) {
    const roles = MOCK_ROLES.filter((r) => input.roleIds.includes(r.id));
    const now = new Date(EPOCH).toISOString();
    const user: User = {
      id: `usr-${String(users.length + 1).padStart(3, '0')}`,
      tenantId: DEFAULT_TENANT,
      name: input.name,
      email: input.email,
      status: 'INVITED', // invite flow assigns INVITED until set-password
      avatar: null,
      roles,
      createdAt: now,
      lastSignInAt: null,
      emailVerifiedAt: null,
      isTrashed: false,
    };
    users = [user, ...users];
    return delay(user);
  },

  async update(id, input) {
    const idx = users.findIndex((u) => u.id === id);
    if (idx === -1) throw new Error('User not found');
    const current = users[idx];
    const roles = input.roleIds ? MOCK_ROLES.filter((r) => input.roleIds!.includes(r.id)) : current.roles;
    const updated: User = {
      ...current,
      name: input.name ?? current.name,
      roles,
      status: input.status ?? current.status,
    };
    users[idx] = updated;
    return delay(updated);
  },

  async trash(ids) {
    users = users.map((u) => (ids.includes(u.id) ? { ...u, isTrashed: true } : u));
    return delay(undefined);
  },

  async restore(ids) {
    users = users.map((u) => (ids.includes(u.id) ? { ...u, isTrashed: false } : u));
    return delay(undefined);
  },

  async invite(ids) {
    // Dev: would send invite emails. Mock just logs the eligible set.
    const eligible = users.filter((u) => ids.includes(u.id) && u.status === 'INVITED');
    console.info('[mock] invite link sent to:', eligible.map((u) => u.email));
    return delay(undefined);
  },

  async resetPassword(id) {
    console.info('[mock] password reset link for:', id);
    return delay(undefined);
  },

  async resendVerification(id) {
    console.info('[mock] verification resent for:', id);
    return delay(undefined);
  },

  async exportCsv(query, columns, ids) {
    const scoped = scopeByStatusView(query);
    const ordered = runQuery(
      scoped,
      { ...query, page: 0, pageSize: Math.max(scoped.length, 1) },
      adapter,
    ).data;
    const rows = ids && ids.length ? ordered.filter((u) => ids.includes(u.id)) : ordered;
    const header = columns.map(csvEscape).join(',');
    const body = rows
      .map((u) => columns.map((c) => csvEscape(columnValue(u, c))).join(','))
      .join('\n');
    return delay(`${header}\n${body}`);
  },
};
