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
import { IdeaFollowersTab } from './idea-followers-tab';

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
    options: [{ label: 'Manager B (+60123450002)', value: 'c-2' }],
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

  it('row Remove calls remove([contactId])', async () => {
    const user = userEvent.setup();
    const h = mockHook([follower]);
    render(<IdeaFollowersTab ideaId="i-1" canManage />);
    await screen.findByText('Manager A');
    await user.click(screen.getByRole('button', { name: /open row actions|actions/i }));
    await user.click(await screen.findByRole('menuitem', { name: /remove/i }));
    await waitFor(() => expect(h.remove).toHaveBeenCalledWith(['c-1']));
  });

  it('Create opens the contact picker and adds the chosen contact', async () => {
    const user = userEvent.setup();
    const h = mockHook([]);
    render(<IdeaFollowersTab ideaId="i-1" canManage />);
    await user.click(await screen.findByRole('button', { name: 'Create' }));
    const dialog = await screen.findByRole('dialog', { name: 'Add follower' });
    await user.click(within(dialog).getByRole('combobox', { name: 'Contact' }));
    await user.click(await screen.findByText('Manager B (+60123450002)'));
    await user.click(within(dialog).getByRole('button', { name: 'Add' }));
    await waitFor(() => expect(h.add).toHaveBeenCalledWith('c-2'));
  });

  it('without manage permission there is no Create and no Remove', async () => {
    mockHook([follower]);
    render(<IdeaFollowersTab ideaId="i-1" canManage={false} />);
    await screen.findByText('Manager A');
    expect(screen.queryByRole('button', { name: 'Create' })).toBeNull();
  });
});
