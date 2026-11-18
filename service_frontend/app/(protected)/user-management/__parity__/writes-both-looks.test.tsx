/**
 * W3-USERS core guarantee: with the Foundryx UIUX switch on, every request
 * these pages send is the same as with it off for the same input. Each case
 * drives the real page (record views with their real hooks, services and
 * `ResourceForm`) through the controls each look shows, records what reaches
 * `lib/api-client` (method, path, body), and compares both looks:
 * create and edit user, role create and edit with several mixed permission
 * grids, team create and edit with members and leads, role user assignment,
 * password reset, resend verification, trash, restore, invitations and
 * impersonation start.
 */
import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { resetPageActionsForTests } from '@/components/fx/actions/page-actions-context';
import { toast } from '@/lib/toast';
import { runResourceAction } from '@/components/platform/resource-actions/run-action';
import { UserFormView } from '../users/components/user-form-view';
import { RoleFormView } from '../roles/components/role-form-view';
import { TeamFormView } from '../teams/components/team-form-view';
import { useUserActions } from '../users/components/use-user-actions';
import { Look, USER, USERS, writes, type RecordedWrite } from './um-kit';

const nav = vi.hoisted(() => ({ path: '/user-management/users' }));
const spies = vi.hoisted(() => ({
  deferredStart: [] as unknown[][],
  impersonate: [] as string[],
}));
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
  useImpersonation: () => ({
    start: async (id: string) => {
      spies.impersonate.push(id);
      return {};
    },
  }),
}));
vi.mock('@/services/terminology-service', () => ({
  terminologyService: { getTerminology: vi.fn().mockResolvedValue({}) },
}));
vi.mock('@/providers/settings-provider', () => ({
  useSettings: () => ({ settings: { container: 'fixed' } }),
}));
vi.mock('@/hooks/use-deferred-action', () => ({
  useDeferredAction: () => ({
    state: { status: 'idle' },
    start: async (...args: unknown[]) => {
      spies.deferredStart.push(args);
      return {};
    },
    cancel: vi.fn(),
  }),
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
  spies.deferredStart.length = 0;
  spies.impersonate.length = 0;
  resetPageActionsForTests();
  document.body.innerHTML = '';
});

type Ui = ReturnType<typeof userEvent.setup>;

/** Renders `ui` in one look, runs `steps`, returns the writes it sent. */
async function sent(
  fx: boolean,
  path: string,
  ui: React.ReactElement,
  ready: string,
  steps: (u: Ui, fx: boolean) => Promise<void>,
): Promise<RecordedWrite[]> {
  nav.path = path;
  writes.length = 0;
  const u = userEvent.setup();
  let unmount!: () => void;
  await act(async () => {
    unmount = render(<Look fx={fx}>{ui}</Look>).unmount;
  });
  await waitFor(() => expect(document.body.textContent).toContain(ready));
  await act(async () => {
    await new Promise((r) => setTimeout(r, 0));
  });
  await steps(u, fx);
  await act(async () => {
    await new Promise((r) => setTimeout(r, 0));
  });
  const out = writes.map((w) => ({ ...w }));
  unmount();
  resetPageActionsForTests();
  document.body.innerHTML = '';
  return out;
}

/** The same steps in both looks: the writes must match, and not be empty. */
async function bothLooks(
  path: string,
  ui: () => React.ReactElement,
  ready: string,
  steps: (u: Ui, fx: boolean) => Promise<void>,
): Promise<RecordedWrite[]> {
  const off = await sent(false, path, ui(), ready, steps);
  const on = await sent(true, path, ui(), ready, steps);
  expect(off.length).toBeGreaterThan(0);
  expect(on).toEqual(off);
  return off;
}

/** The form row holding the visible label `text`: the nearest ancestor with exactly one `has`. */
function rowOf(text: string, has: string): HTMLElement {
  const labels = screen.getAllByText(text, { exact: true });
  for (const label of labels) {
    let el: HTMLElement | null = label;
    for (let i = 0; i < 5 && el; i += 1) {
      const found = el.querySelectorAll(has).length;
      if (found === 1) return el;
      if (found > 1) break;
      el = el.parentElement;
    }
  }
  throw new Error(`No row "${text}" holding ${has}`);
}

async function pickOptions(u: Ui, rowLabel: string, names: string[]) {
  await u.click(within(rowOf(rowLabel, '[role=combobox]')).getByRole('combobox'));
  for (const name of names) await u.click(await screen.findByRole('option', { name }));
  await u.keyboard('{Escape}');
}

async function typeInto(u: Ui, placeholder: string, text: string) {
  const input = screen.getByPlaceholderText(placeholder);
  await u.clear(input);
  await u.type(input, text);
}

/** Save / Create: the record card's button while off, the red action while on. */
async function save(u: Ui, fx: boolean, offLabel: string) {
  if (fx) {
    const red = document.querySelector<HTMLElement>('[data-fx-main-action] button');
    expect(red).not.toBeNull();
    await u.click(red!);
  } else {
    await u.click(screen.getByRole('button', { name: offLabel }));
  }
  await act(async () => {
    await new Promise((r) => setTimeout(r, 0));
  });
}

async function openTab(u: Ui, name: string) {
  await u.click(screen.getByRole('tab', { name }));
}

/* ------------------------------------------------------------ permissions */

type GridOp = { res: string; action: string } | { res: string; all: true };

/** One tick in the grid: today's dropdown while off, a tick box while on. */
async function tick(u: Ui, fx: boolean, op: GridOp) {
  if (fx) {
    const row = screen.getByRole('group', { name: op.res });
    const name = 'all' in op ? 'All' : op.action;
    await u.click(within(row).getByRole('checkbox', { name }));
    return;
  }
  const row = rowOf(op.res, '[role=combobox]');
  await u.click(within(row).getByRole('combobox'));
  if ('all' in op) {
    const button =
      screen.queryByRole('button', { name: 'Select all' }) ??
      screen.getByRole('button', { name: 'Clear all' });
    await u.click(button);
  } else {
    await u.click(await screen.findByRole('option', { name: op.action }));
  }
  await u.keyboard('{Escape}');
}

const GRIDS: { name: string; ops: GridOp[] }[] = [
  {
    name: 'a write implies read, a write taken off, an export',
    ops: [
      { res: 'Users', action: 'Create' },
      { res: 'Users', action: 'Update' },
      { res: 'Contacts', action: 'Export' },
    ],
  },
  {
    name: 'All on one resource, one off again, read only on another',
    ops: [
      { res: 'Roles', all: true },
      { res: 'Roles', action: 'Delete' },
      { res: 'Contacts', action: 'Read' },
    ],
  },
  {
    name: 'All twice clears, writes taken off leave read',
    ops: [
      { res: 'Users', all: true },
      { res: 'Users', all: true },
      { res: 'Contacts', action: 'Create' },
      { res: 'Contacts', action: 'Create' },
      { res: 'Roles', action: 'Update' },
    ],
  },
];

describe('the same input sends the same requests in both looks', () => {
  it('creates a user', async () => {
    const [w] = await bothLooks('/user-management/users/new', () => <UserFormView initialEditing />, 'New user', async (u, fx) => {
      await typeInto(u, 'Full name', 'Nur Aisyah');
      await typeInto(u, 'name@company.com', 'nur@example.com');
      await pickOptions(u, 'Roles', ['Admin']);
      await save(u, fx, 'Create user');
    });
    expect(w).toEqual({
      method: 'POST',
      path: '/users',
      body: { name: 'Nur Aisyah', email: 'nur@example.com', roleIds: ['r-2'], status: 'ACTIVE' },
    });
  });

  it('edits a user', async () => {
    const [w] = await bothLooks('/user-management/users/u-2', () => <UserFormView userId="u-2" initialEditing />, 'Jane Doe', async (u, fx) => {
      await typeInto(u, 'Full name', 'Jane Tan');
      await pickOptions(u, 'Roles', ['Admin']);
      await save(u, fx, 'Save user');
    });
    expect(w.method).toBe('PATCH');
    expect(w.path).toBe('/users/u-2');
    expect(w.body).toEqual({ name: 'Jane Tan', email: 'jane@example.com', roleIds: ['r-1', 'r-2'], status: 'ACTIVE' });
  });

  for (const grid of GRIDS) {
    it(`creates a role: ${grid.name}`, async () => {
      const out = await bothLooks('/user-management/roles/new', () => <RoleFormView initialEditing />, 'New role', async (u, fx) => {
        await typeInto(u, 'e.g. Event Manager', 'Desk');
        await openTab(u, 'Permissions');
        for (const op of grid.ops) await tick(u, fx, op);
        await save(u, fx, 'Create role');
      });
      expect(out).toHaveLength(1);
      expect(out[0].method).toBe('POST');
    });

    it(`edits a role: ${grid.name}`, async () => {
      const out = await bothLooks('/user-management/roles/r-1', () => <RoleFormView roleId="r-1" initialEditing />, 'Omnichannel', async (u, fx) => {
        for (const op of grid.ops) await tick(u, fx, op);
        await save(u, fx, 'Save role');
      });
      expect(out).toHaveLength(1);
      expect(out[0].method).toBe('PATCH');
    });
  }

  it('the first mixed grid sends exactly these keys', async () => {
    const [w] = await bothLooks('/user-management/roles/r-1', () => <RoleFormView roleId="r-1" initialEditing />, 'Omnichannel', async (u, fx) => {
      for (const op of GRIDS[0].ops) await tick(u, fx, op);
      await save(u, fx, 'Save role');
    });
    // Starts from users.read, users.update, contacts.read: Create added,
    // Update taken off, Export added (read stays with it).
    expect((w.body as { permissionKeys: string[] }).permissionKeys).toEqual([
      'users.read',
      'users.create',
      'contacts.read',
      'contacts.export',
    ]);
  });

  it('creates a team with members and a lead', async () => {
    const [w] = await bothLooks('/user-management/teams/new', () => <TeamFormView initialEditing />, 'New team', async (u, fx) => {
      await typeInto(u, 'Team name', 'Night shift');
      await typeInto(u, 'What this team handles', 'After hours');
      await pickOptions(u, 'Members', ['Jane Doe', 'Kay Tan']);
      await pickOptions(u, 'Leads', ['Kay Tan']);
      await save(u, fx, 'Create team');
    });
    expect(w).toEqual({
      method: 'POST',
      path: '/teams',
      body: {
        name: 'Night shift',
        description: 'After hours',
        isActive: true,
        members: [
          { userId: 'u-2', role: 'member' },
          { userId: 'u-4', role: 'lead' },
        ],
      },
    });
  });

  it('edits a team: membership and status', async () => {
    const [w] = await bothLooks('/user-management/teams/tm-1', () => <TeamFormView teamId="tm-1" initialEditing />, 'Support', async (u, fx) => {
      await pickOptions(u, 'Members', ['Jane Doe', 'Kay Tan']);
      await u.click(within(rowOf('Status', '[role=switch]')).getByRole('switch'));
      await save(u, fx, 'Save team');
    });
    expect(w.method).toBe('PATCH');
    expect(w.body).toEqual({
      name: 'Support',
      description: 'First line',
      isActive: false,
      members: [
        { userId: 'u-3', role: 'member' },
        { userId: 'u-4', role: 'member' },
      ],
    });
  });

  it('assigns and unassigns users on a role', async () => {
    const out = await bothLooks('/user-management/roles/r-1', () => <RoleFormView roleId="r-1" initialEditing={false} />, 'Omnichannel', async (u) => {
      await openTab(u, 'Assigned Users');
      await screen.findByText('jane@example.com');
      await u.click(screen.getAllByRole('combobox').find((c) => c.textContent?.includes('Select users'))!);
      await u.click(await screen.findByRole('option', { name: /Lim Wei Jie/ }));
      await u.keyboard('{Escape}');
      await u.click(screen.getByRole('button', { name: 'Assign user' }));
      await u.click(await screen.findByRole('button', { name: 'Unassign Jane Doe' }));
    });
    expect(out).toEqual([
      { method: 'POST', path: '/roles/r-1/users', body: { userIds: ['u-3'] } },
      { method: 'DELETE', path: '/roles/r-1/users/u-2', body: null },
    ]);
  });

  it('under the switch, assigning names who joined which role, and Undo sends the existing removal', async () => {
    const fxDone = vi.spyOn(toast, 'fxDone');
    await sent(true, '/user-management/roles/r-1', <RoleFormView roleId="r-1" initialEditing={false} />, 'Omnichannel', async (u) => {
      await openTab(u, 'Assigned Users');
      await screen.findByText('jane@example.com');
      await u.click(screen.getAllByRole('combobox').find((c) => c.textContent?.includes('Select users'))!);
      await u.click(await screen.findByRole('option', { name: /Lim Wei Jie/ }));
      await u.keyboard('{Escape}');
      await u.click(screen.getByRole('button', { name: 'Assign user' }));
      expect(fxDone).toHaveBeenCalledWith(
        expect.objectContaining({ what: 'Lim Wei Jie added to Sales desk', byWhom: 'you' }),
      );
      writes.length = 0;
      await act(async () => {
        fxDone.mock.calls[0][0].undo?.();
        await new Promise((r) => setTimeout(r, 0));
      });
      expect(writes).toEqual([{ method: 'DELETE', path: '/roles/r-1/users/u-3', body: null }]);
    });
    fxDone.mockRestore();
  });

  /** A record action: the gear menu while off; an icon or More while on. */
  async function recordAction(u: Ui, fx: boolean, label: string) {
    if (!fx) {
      await u.click(screen.getByRole('button', { name: 'Actions' }));
      await u.click(await screen.findByRole('menuitem', { name: label }));
      return;
    }
    const icon = screen.queryByRole('button', { name: label });
    if (icon) {
      await u.click(icon);
      return;
    }
    await u.click(screen.getByRole('button', { name: 'More' }));
    await u.click(await screen.findByRole('menuitem', { name: label }));
  }

  for (const [label, path] of [
    ['Reset password', '/users/u-2/reset-password'],
    ['Resend verification', '/users/u-2/resend-verification'],
  ] as const) {
    it(`${label} from the user record`, async () => {
      const out = await bothLooks('/user-management/users/u-2', () => <UserFormView userId="u-2" initialEditing={false} />, 'jane@example.com', async (u, fx) => {
        await recordAction(u, fx, label);
      });
      expect(out).toEqual([{ method: 'POST', path, body: null }]);
    });
  }

  it('Trash from the user record parks the same deferred action', async () => {
    const calls: unknown[][][] = [];
    for (const fx of [false, true]) {
      await sent(fx, '/user-management/users/u-2', <UserFormView userId="u-2" initialEditing={false} />, 'jane@example.com', async (u) => {
        await recordAction(u, fx, 'Trash');
      });
      calls.push(spies.deferredStart.map((c) => [...c]));
      spies.deferredStart.length = 0;
    }
    expect(calls[0]).toEqual([['users.trash', [{ entityType: 'user', entityId: 'u-2' }], undefined]]);
    expect(calls[1]).toEqual(calls[0]);
  });
});

/* ------------------------------------------------------- list and row actions */

function actionsIn(fx: boolean) {
  let out!: ReturnType<typeof useUserActions>;
  function Grab() {
    out = useUserActions();
    return null;
  }
  render(
    <Look fx={fx}>
      <Grab />
    </Look>,
  );
  return out;
}

describe('user row and bulk actions run the same requests in both looks', () => {
  const trashed = USERS.map((u) => ({ ...u, isTrashed: true }));
  const cases: { id: string; rows: typeof USERS }[] = [
    { id: 'send-invitation', rows: USERS },
    { id: 'restore', rows: trashed },
    { id: 'reset-password', rows: [USER] },
    { id: 'resend-verification', rows: [USER] },
  ];
  for (const c of cases) {
    it(c.id, async () => {
      const results: RecordedWrite[][] = [];
      for (const fx of [false, true]) {
        writes.length = 0;
        const action = actionsIn(fx).find((a) => a.id === c.id)!;
        await act(async () => {
          await runResourceAction(action, c.rows, { reload: () => {} });
        });
        results.push(writes.map((w) => ({ ...w })));
        document.body.innerHTML = '';
      }
      expect(results[0].length).toBeGreaterThan(0);
      expect(results[1]).toEqual(results[0]);
    });
  }

  it('impersonation starts for the same user', async () => {
    const started: string[][] = [];
    for (const fx of [false, true]) {
      spies.impersonate.length = 0;
      const action = actionsIn(fx).find((a) => a.id === 'impersonate')!;
      const reload = vi.fn();
      vi.stubGlobal('location', { ...window.location, reload });
      await act(async () => {
        await runResourceAction(action, [USER], { reload: () => {} });
      });
      vi.unstubAllGlobals();
      started.push([...spies.impersonate]);
      document.body.innerHTML = '';
    }
    expect(started[0]).toEqual(['u-2']);
    expect(started[1]).toEqual(started[0]);
  });

  it('trash parks the same deferred action key and entity type', () => {
    const [off, on] = [false, true].map((fx) => actionsIn(fx).find((a) => a.id === 'trash')!.deferred);
    expect({ key: on?.actionKey, type: on?.entityType, payload: on?.payload }).toEqual({
      key: off?.actionKey,
      type: off?.entityType,
      payload: off?.payload,
    });
  });
});
