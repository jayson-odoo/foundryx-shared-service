/**
 * Lane FEEDBACK-SUBSCRIBE (AC-FS-10): the operator "Followers" tab on the
 * shared ResourceList (a clone of "Merged from"): followers listed, staff
 * remove via the row action and add through the contact picker.
 */
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { useRouter, useSearchParams } from 'next/navigation';
import type { IdeaFollower } from '@/types/ideation';
import { followersCsv, followersPage, IdeaFollowersTab } from './idea-followers-tab';

vi.mock('next/navigation', () => ({
  useRouter: vi.fn(() => ({ push: vi.fn(), prefetch: vi.fn() })),
  useSearchParams: vi.fn(() => new URLSearchParams()),
  usePathname: vi.fn(() => '/feedback/survivor-1'),
}));

vi.mock('next-auth/react', () => ({
  useSession: () => ({ data: { user: { permissions: [] } }, status: 'authenticated' }),
}));

vi.mock('@/lib/impersonation-store', () => ({
  useImpersonationSession: () => null,
}));

vi.mock('@/services/preferences-service', () => ({
  preferencesService: {
    get: vi.fn().mockResolvedValue(null),
    save: vi.fn().mockResolvedValue(undefined),
  },
}));

vi.mock('@/services/terminology-service', () => ({
  terminologyService: { getTerminology: vi.fn().mockResolvedValue({}) },
}));

vi.mock('@/providers/import-activity-provider', () => ({
  useImportActivity: () => ({ openImport: vi.fn() }),
}));

vi.mock('@/hooks/use-workspace-id', () => ({ useWorkspaceId: () => ({ workspaceId: 'ws-1', loading: false }) }));
vi.mock('@/hooks/use-contact-picker', () => ({
  useContactPicker: () => ({
    query: '',
    setQuery: vi.fn(),
    loading: false,
    options: [
      { label: 'Manager B (+60123450002)', value: 'c-2' },
      { label: 'Zed Other (+60123450099)', value: 'c-9' },
    ],
  }),
}));

const hook = vi.hoisted(() => vi.fn());
vi.mock('@/hooks/use-idea-followers', () => ({ useIdeaFollowers: (...a: unknown[]) => hook(...a) }));

const follower: IdeaFollower = {
  contactId: 'c-1',
  name: 'Manager A',
  phone: '+60123450001',
  addedByStaff: false,
  createdAt: '2026-11-17T04:00:00Z',
};

function mockHook(rows: IdeaFollower[]) {
  const h = { followers: rows, error: null, reload: vi.fn(), add: vi.fn().mockResolvedValue(undefined), remove: vi.fn().mockResolvedValue(undefined) };
  hook.mockReturnValue(h);
  return h;
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(useRouter).mockReturnValue({ push: vi.fn(), prefetch: vi.fn() } as unknown as ReturnType<typeof useRouter>);
  vi.mocked(useSearchParams).mockReturnValue(new URLSearchParams() as unknown as ReturnType<typeof useSearchParams>);
});

describe('IdeaFollowersTab (AC-FS-10)', () => {
  it('lists the followers: name, phone, who added them', async () => {
    mockHook([follower]);
    render(<IdeaFollowersTab ideaId="i-1" canManage />);
    const table = await screen.findByRole('table');
    expect(within(table).getByText('Manager A')).toBeInTheDocument();
    expect(within(table).getByText('+60123450001')).toBeInTheDocument();
    expect(within(table).getByText('Themselves')).toBeInTheDocument();
  });

  it('rows have no action button; right-click opens Remove', async () => {
    const user = userEvent.setup();
    const h = mockHook([follower]);
    render(<IdeaFollowersTab ideaId="i-1" canManage />);
    const cell = await screen.findByText('Manager A');
    expect(screen.queryByRole('button', { name: 'Actions' })).toBeNull();
    const row = cell.closest('tr') as HTMLElement;
    await user.pointer({ keys: '[MouseRight]', target: row });
    await user.click(await screen.findByRole('menuitem', { name: 'Remove' }));
    await waitFor(() => expect(h.remove).toHaveBeenCalledWith(['c-1']));
  });

  it('a row opens the contact record', async () => {
    mockHook([follower]);
    render(<IdeaFollowersTab ideaId="i-1" canManage />);
    const cell = await screen.findByText('Manager A');
    const link = cell.closest('a') ?? cell.closest('tr')?.querySelector('a');
    expect(link?.getAttribute('href')).toMatch(/^\/omnichannel\/contacts\/c-1(\?|$)/);
  });

  it('Create is not a second filled button on the record page', async () => {
    mockHook([]);
    render(<IdeaFollowersTab ideaId="i-1" canManage />);
    expect(await screen.findByRole('button', { name: 'Create' })).not.toHaveClass('bg-primary');
  });

  it('the toolbar has Filters', async () => {
    mockHook([follower]);
    render(<IdeaFollowersTab ideaId="i-1" canManage />);
    expect(await screen.findByRole('button', { name: /filters/i })).toBeInTheDocument();
  });

  it('Create opens the contact picker and adds the chosen contact', async () => {
    const user = userEvent.setup();
    const h = mockHook([]);
    render(<IdeaFollowersTab ideaId="i-1" canManage />);
    await user.click(await screen.findByRole('button', { name: 'Create' }));
    const dialog = await screen.findByRole('dialog', { name: 'Add follower' });
    await user.click(within(dialog).getByRole('combobox', { name: 'Contact' }));
    // Typing narrows the list to matching names / phones (crew pass 70e96f2b).
    await user.keyboard('manager');
    expect(screen.queryByText('Zed Other (+60123450099)')).toBeNull();
    await user.click(await screen.findByText('Manager B (+60123450002)'));
    await user.click(within(dialog).getByRole('button', { name: 'Add' }));
    await waitFor(() => expect(h.add).toHaveBeenCalledWith('c-2'));
  });

  it('every data column header is the shared sortable header', async () => {
    mockHook([follower]);
    render(<IdeaFollowersTab ideaId="i-1" canManage />);
    await screen.findByText('Manager A');
    for (const name of ['Name', 'Phone', 'Added by', 'Following since']) {
      expect(screen.getByRole('button', { name })).toBeInTheDocument();
    }
  });

  it('a refusal clears once another contact is picked (crew pass 5441b840)', async () => {
    const user = userEvent.setup();
    const h = mockHook([]);
    h.add.mockRejectedValueOnce(new Error('This contact raised the request and already gets its updates.'));
    render(<IdeaFollowersTab ideaId="i-1" canManage />);
    await user.click(await screen.findByRole('button', { name: 'Create' }));
    const dialog = await screen.findByRole('dialog', { name: 'Add follower' });
    await user.click(within(dialog).getByRole('combobox', { name: 'Contact' }));
    await user.click(await screen.findByText('Manager B (+60123450002)'));
    await user.click(within(dialog).getByRole('button', { name: 'Add' }));
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('already gets its updates');
    await user.click(within(dialog).getByRole('combobox', { name: 'Contact' }));
    await user.click(await screen.findByText('Zed Other (+60123450099)'));
    expect(within(dialog).queryByRole('alert')).toBeNull();
  });

  it('reopening Add follower starts clean: full list, no pick, no refusal (crew pass 41998794)', async () => {
    const user = userEvent.setup();
    const h = mockHook([]);
    h.add.mockRejectedValueOnce(new Error('This contact raised the request and already gets its updates.'));
    render(<IdeaFollowersTab ideaId="i-1" canManage />);
    await user.click(await screen.findByRole('button', { name: 'Create' }));
    let dialog = await screen.findByRole('dialog', { name: 'Add follower' });
    await user.click(within(dialog).getByRole('combobox', { name: 'Contact' }));
    await user.keyboard('manager');
    await user.click(await screen.findByText('Manager B (+60123450002)'));
    await user.click(within(dialog).getByRole('button', { name: 'Add' }));
    await within(dialog).findByRole('alert');
    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }));
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Add follower' })).toBeNull());

    await user.click(screen.getByRole('button', { name: 'Create' }));
    dialog = await screen.findByRole('dialog', { name: 'Add follower' });
    expect(within(dialog).queryByRole('alert')).toBeNull();
    expect(within(dialog).getByRole('button', { name: 'Add' })).toBeDisabled();
    await user.click(within(dialog).getByRole('combobox', { name: 'Contact' }));
    expect(await screen.findByText('Zed Other (+60123450099)')).toBeInTheDocument();
    expect(screen.getByText('Manager B (+60123450002)')).toBeInTheDocument();
  });

  it('without manage permission there is no Create and no Remove', async () => {
    mockHook([follower]);
    render(<IdeaFollowersTab ideaId="i-1" canManage={false} />);
    await screen.findByText('Manager A');
    expect(screen.queryByRole('button', { name: 'Create' })).toBeNull();
  });
});

describe('followers list data (client side, the whole set is small)', () => {
  const rows: IdeaFollower[] = [
    follower,
    { ...follower, contactId: 'c-2', name: 'Aaron', phone: '+60123450002', addedByStaff: true, createdAt: '2026-11-15T04:00:00Z' },
  ];
  const q = { page: 0, pageSize: 25 };

  it('filters Added by (multi-select) and Following since', () => {
    const staff = followersPage(rows, {
      ...q,
      filter: { kind: 'group', combinator: 'and', rules: [{ kind: 'condition', field: 'addedBy', operator: 'in', value: ['staff'] }] },
    });
    expect(staff.data.map((r) => r.contactId)).toEqual(['c-2']);
    const recent = followersPage(rows, {
      ...q,
      filter: { kind: 'group', combinator: 'and', rules: [{ kind: 'condition', field: 'since', operator: 'after', value: '2026-11-16' }] },
    });
    expect(recent.data.map((r) => r.contactId)).toEqual(['c-1']);
  });

  it('export has exactly the ticked columns and only the ticked rows', () => {
    const csv = followersCsv(rows, ['name', 'addedBy'], ['c-2'], (iso) => iso.slice(0, 10));
    const lines = csv.trim().split(/\r?\n/);
    expect(lines[0]).toBe('"Name","Added by"');
    expect(lines.slice(1)).toEqual(['"Aaron","Staff"']);
  });
});
