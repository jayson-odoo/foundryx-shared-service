/**
 * Switch-off parity for the user-management pages (users, roles, teams; see
 * components/fx/__parity__/parity-utils.ts). Recorded on the code before the
 * W3-USERS slice: the lists, each record read and editing, and each new
 * form, rendered with the Foundryx UIUX switch off. A change that needs one
 * of these snapshots updated changes what a user sees today: fix the code,
 * never the snapshot.
 */
import type { ReactElement } from 'react';
import { act, render, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { parityHtml } from '@/components/fx/__parity__/parity-utils';
import UsersPage from '../users/page';
import RolesPage from '../roles/page';
import TeamsPage from '../teams/page';
import { UserFormView } from '../users/components/user-form-view';
import { RoleFormView } from '../roles/components/role-form-view';
import { TeamFormView } from '../teams/components/team-form-view';
import { Look, writes } from './um-kit';

const nav = vi.hoisted(() => ({ path: '/user-management/users' }));
const perms = vi.hoisted(() => [
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
]);

vi.mock('next/navigation', () => ({
  usePathname: vi.fn(() => nav.path),
  useSearchParams: vi.fn(() => new URLSearchParams()),
  useParams: vi.fn(() => ({})),
  useRouter: vi.fn(() => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn(), back: vi.fn() })),
  notFound: vi.fn(() => {
    throw new Error('NEXT_NOT_FOUND');
  }),
}));
vi.mock('next-auth/react', () => ({
  useSession: () => ({
    data: { user: { id: 'me', name: 'Demo Admin', permissions: perms } },
    status: 'authenticated',
  }),
}));
vi.mock('next-themes', () => ({
  useTheme: () => ({ theme: 'light', setTheme: vi.fn() }),
}));
vi.mock('@/lib/impersonation-store', () => ({
  useImpersonationSession: () => null,
}));
vi.mock('@/hooks/use-impersonation', () => ({
  useImpersonation: () => ({ start: vi.fn() }),
}));
vi.mock('@/services/terminology-service', () => ({
  terminologyService: { getTerminology: vi.fn().mockResolvedValue({}) },
}));
vi.mock('@/providers/settings-provider', () => ({
  useSettings: () => ({ settings: { container: 'fixed' } }),
}));
vi.mock('@/hooks/use-deferred-action', () => ({
  useDeferredAction: () => ({ state: { status: 'idle' }, start: vi.fn(async () => ({})), cancel: vi.fn() }),
}));
vi.mock('@/lib/api-client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api-client')>();
  const kit = await import('./um-kit');
  return {
    ...actual,
    apiFetch: vi.fn(kit.fakeApiFetch),
    apiFetchText: vi.fn(async () => ''),
  };
});

afterEach(() => {
  writes.length = 0;
});

async function snapOff(path: string, ui: ReactElement, ready: (root: HTMLElement) => boolean) {
  nav.path = path;
  let utils!: ReturnType<typeof render>;
  await act(async () => {
    utils = render(<Look fx={false}>{ui}</Look>);
  });
  await waitFor(() => expect(ready(utils.container)).toBe(true));
  // Let late reads (role options, assigned users) settle.
  await act(async () => {
    await new Promise((r) => setTimeout(r, 0));
  });
  const html = parityHtml(utils.container);
  utils.unmount();
  return html;
}

const hasText = (text: string) => (root: HTMLElement) => root.textContent?.includes(text) ?? false;

describe('user-management switch-off parity', () => {
  it('users list', async () => {
    expect(await snapOff('/user-management/users', <UsersPage />, hasText('Lim Wei Jie'))).toMatchSnapshot();
  });

  it('roles list', async () => {
    expect(await snapOff('/user-management/roles', <RolesPage />, hasText('Sales desk'))).toMatchSnapshot();
  });

  it('teams list', async () => {
    expect(await snapOff('/user-management/teams', <TeamsPage />, hasText('Support'))).toMatchSnapshot();
  });

  it('user record, read', async () => {
    expect(await snapOff('/user-management/users/u-2', <UserFormView userId="u-2" initialEditing={false} />, hasText('jane@example.com'))).toMatchSnapshot();
  });

  it('user record, editing', async () => {
    expect(await snapOff('/user-management/users/u-2', <UserFormView userId="u-2" initialEditing />, hasText('Jane Doe'))).toMatchSnapshot();
  });

  it('new user', async () => {
    expect(await snapOff('/user-management/users/new', <UserFormView initialEditing />, hasText('New user'))).toMatchSnapshot();
  });

  it('role record, read (permissions)', async () => {
    expect(await snapOff('/user-management/roles/r-1', <RoleFormView roleId="r-1" initialEditing={false} />, hasText('Omnichannel'))).toMatchSnapshot();
  });

  it('role record, editing (permissions)', async () => {
    expect(await snapOff('/user-management/roles/r-1', <RoleFormView roleId="r-1" initialEditing />, hasText('Omnichannel'))).toMatchSnapshot();
  });

  it('new role', async () => {
    expect(await snapOff('/user-management/roles/new', <RoleFormView initialEditing />, hasText('New role'))).toMatchSnapshot();
  });

  it('team record, read', async () => {
    expect(await snapOff('/user-management/teams/tm-1', <TeamFormView teamId="tm-1" initialEditing={false} />, hasText('First line'))).toMatchSnapshot();
  });

  it('team record, editing', async () => {
    expect(await snapOff('/user-management/teams/tm-1', <TeamFormView teamId="tm-1" initialEditing />, hasText('Support'))).toMatchSnapshot();
  });

  it('new team', async () => {
    expect(await snapOff('/user-management/teams/new', <TeamFormView initialEditing />, hasText('New team'))).toMatchSnapshot();
  });
});
