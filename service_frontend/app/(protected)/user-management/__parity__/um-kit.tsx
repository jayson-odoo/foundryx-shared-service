/**
 * Test kit for the user-management pages (users, roles, teams): fixed records,
 * a stand-in for `lib/api-client` that answers reads from them and records
 * every write (method, path, body), and a wrapper that renders a page with
 * the Foundryx UIUX switch on or off. Used by the switch-off parity snapshots
 * and by the tests that compare what both looks send.
 */
import type { ReactNode } from 'react';
import { FX_DEFAULT_THEME } from '@/lib/fx/cookies';
import { FxProvider } from '@/providers/fx-provider';
import type { PermissionCatalog } from '@/types/permission';
import type { RoleDetail, RoleListItem, RoleUser, AssignableUser } from '@/types/role';
import type { Team } from '@/types/team';
import type { User } from '@/types/user';

export const T0 = '2026-03-04T05:06:07Z';

export const CATALOG: PermissionCatalog = [
  {
    resource: 'users',
    resourceLabel: 'Users',
    module: 'core',
    moduleLabel: 'Core',
    actions: [
      { key: 'users.read', action: 'read', actionLabel: 'Read', description: null },
      { key: 'users.create', action: 'create', actionLabel: 'Create', description: null },
      { key: 'users.update', action: 'update', actionLabel: 'Update', description: null },
      { key: 'users.delete', action: 'delete', actionLabel: 'Delete', description: null },
      { key: 'users.impersonate', action: 'impersonate', actionLabel: 'Impersonate', description: null },
    ],
  },
  {
    resource: 'roles',
    resourceLabel: 'Roles',
    module: 'core',
    moduleLabel: 'Core',
    actions: [
      { key: 'roles.read', action: 'read', actionLabel: 'Read', description: null },
      { key: 'roles.create', action: 'create', actionLabel: 'Create', description: null },
      { key: 'roles.update', action: 'update', actionLabel: 'Update', description: null },
      { key: 'roles.delete', action: 'delete', actionLabel: 'Delete', description: null },
    ],
  },
  {
    resource: 'contacts',
    resourceLabel: 'Contacts',
    module: 'omnichannel',
    moduleLabel: 'Omnichannel',
    actions: [
      { key: 'contacts.read', action: 'read', actionLabel: 'Read', description: null },
      { key: 'contacts.create', action: 'create', actionLabel: 'Create', description: null },
      { key: 'contacts.export', action: 'export', actionLabel: 'Export', description: null },
    ],
  },
];

export const ROLE: RoleDetail = {
  id: 'r-1',
  name: 'Sales desk',
  description: 'Sells things',
  isSystem: false,
  userCount: 2,
  permissionCount: 3,
  createdAt: T0,
  permissionKeys: ['users.read', 'users.update', 'contacts.read'],
};

export const ROLE_ROW: RoleListItem = {
  id: ROLE.id,
  name: ROLE.name,
  description: ROLE.description,
  isSystem: false,
  userCount: 2,
  permissionCount: 3,
  createdAt: T0,
};

export const ROLE_USERS: RoleUser[] = [
  { id: 'u-2', name: 'Jane Doe', email: 'jane@example.com', avatar: null, status: 'ACTIVE', assignedAt: T0 },
];

export const ASSIGNABLE: AssignableUser[] = [
  { id: 'u-3', name: 'Lim Wei Jie', email: 'wei@example.com', avatar: null, status: 'ACTIVE' },
  { id: 'u-4', name: 'Kay Tan', email: 'kay@example.com', avatar: null, status: 'INVITED' },
];

export const USER: User = {
  id: 'u-2',
  tenantId: 't-1',
  name: 'Jane Doe',
  email: 'jane@example.com',
  status: 'ACTIVE',
  avatar: null,
  roles: [{ id: 'r-1', name: 'Sales desk' }],
  createdAt: T0,
  lastSignInAt: null,
  emailVerifiedAt: null,
  isTrashed: false,
};

export const USERS: User[] = [
  USER,
  {
    ...USER,
    id: 'u-3',
    name: 'Lim Wei Jie',
    email: 'wei@example.com',
    roles: [],
    emailVerifiedAt: T0,
    lastSignInAt: T0,
  },
  { ...USER, id: 'u-4', name: 'Kay Tan', email: 'kay@example.com', status: 'INVITED', roles: [] },
];

export const ROLE_OPTIONS = [
  { id: 'r-1', name: 'Sales desk' },
  { id: 'r-2', name: 'Admin' },
];

export const TEAM: Team = {
  id: 'tm-1',
  name: 'Support',
  description: 'First line',
  isActive: true,
  sortOrder: 0,
  members: [
    { userId: 'u-2', name: 'Jane Doe', email: 'jane@example.com', role: 'lead' },
    { userId: 'u-3', name: 'Lim Wei Jie', email: 'wei@example.com', role: 'member' },
  ],
  memberCount: 2,
  createdAt: T0,
  updatedAt: T0,
};

/** Every permission the demo admin holds that these pages read. */
export const ALL_PERMISSIONS = [
  'users.read',
  'users.create',
  'users.update',
  'users.delete',
  'users.impersonate',
  'roles.read',
  'roles.create',
  'roles.update',
  'roles.delete',
  'teams.read',
  'teams.manage',
];

export interface RecordedWrite {
  method: string;
  path: string;
  body: unknown;
}

/** Writes seen by the stand-in api client, in order. */
export const writes: RecordedWrite[] = [];

function list<T>(data: T[]) {
  return { data, total: data.length, page: 0, pageSize: 50 };
}

/** Answers a read from the fixtures above. */
function read(path: string): unknown {
  const p = path.split('?')[0];
  if (p === '/permissions') return CATALOG;
  if (p === '/roles/options') return ROLE_OPTIONS;
  if (p === '/roles') return list([ROLE_ROW]);
  if (p === '/roles/at') return { role: ROLE, total: 1 };
  if (p === `/roles/${ROLE.id}`) return ROLE;
  if (p === `/roles/${ROLE.id}/users`) return ROLE_USERS;
  if (p === `/roles/${ROLE.id}/assignable`) return ASSIGNABLE;
  if (p === '/users') return list(USERS);
  if (p === '/users/at') return { user: USER, total: USERS.length };
  const user = USERS.find((u) => p === `/users/${u.id}`);
  if (user) return user;
  if (p === '/teams') return list([TEAM]);
  if (p === '/teams/at') return { team: TEAM, total: 1 };
  if (p === `/teams/${TEAM.id}`) return TEAM;
  return null;
}

/** What a write answers with (the created or updated record). */
function answer(method: string, path: string, body: unknown): unknown {
  const b = (body ?? {}) as Record<string, unknown>;
  if (path === '/roles' && method === 'POST') return { ...ROLE, id: 'r-new', ...b };
  if (path === `/roles/${ROLE.id}` && method === 'PATCH') return { ...ROLE, ...b };
  if (path === '/users' && method === 'POST') return { ...USER, id: 'u-new', ...b, roles: [] };
  if (path.startsWith('/users/') && method === 'PATCH') return { ...USER, ...b, roles: USER.roles };
  if (path === '/teams' && method === 'POST') return { ...TEAM, id: 'tm-new', name: b.name };
  if (path === `/teams/${TEAM.id}` && method === 'PATCH') return { ...TEAM, name: b.name ?? TEAM.name };
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

/** Renders `children` with the switch on (`fx`) or off. */
export function Look({ fx, children }: { fx: boolean; children: ReactNode }) {
  return (
    <FxProvider initial={fx} initialTheme={FX_DEFAULT_THEME}>
      {children}
    </FxProvider>
  );
}
