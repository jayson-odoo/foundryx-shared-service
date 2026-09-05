/**
 * Contacts list host (D-A2-1, AC-CTM-46 permission gating) - the
 * "Manage segments" action is gated `segments.manage` (`page.tsx`'s
 * `canManageSegments`): it must stay hidden even when saved segments exist
 * for a user who lacks the permission, and appear once granted. UX gate only
 * (the backend `segments.manage` requirement on the write routes is the real
 * boundary) - mirrors the same discipline as `contacts.manage`/`contacts.import`
 * covered in `use-contact-actions.test.tsx` / `use-contacts-list-config.test.tsx`.
 */
import { render as rtlRender, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { SettingsProvider } from '@/providers/settings-provider';
import type { ContactSegment } from '@/types/omnichannel';
import ContactsPage from './page';

function render(ui: React.ReactElement) {
  return rtlRender(<SettingsProvider>{ui}</SettingsProvider>);
}

let permissions = new Set<string>();
vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({ can: (key: string) => permissions.has(key), ready: true, permissions }),
}));
vi.mock('@/hooks/use-datetime', () => ({
  useDatetime: () => ({
    formatDate: (v: string) => v,
    formatDateTime: (v: string) => v,
    formatTime: (v: string) => v,
  }),
}));
vi.mock('@/hooks/use-terminology', () => ({
  useTerminology: () => ({
    ready: true,
    label: (k: string) => k,
    labelPlural: (k: string) => k,
    t: (k: string) => k,
    refetch: vi.fn(),
  }),
}));

vi.mock('@/hooks/use-contacts', () => ({
  useActiveWorkspace: () => ({
    workspaceId: 'wsp-1',
    workspaces: [],
    ready: true,
    setWorkspaceId: vi.fn(),
  }),
}));

const SEGMENTS: ContactSegment[] = [
  {
    id: 'seg-1',
    workspaceId: 'wsp-1',
    name: 'Urgent & high priority',
    description: null,
    filter: { kind: 'group', combinator: 'and', rules: [] },
    createdAt: '2026-01-01T00:00:00Z',
    updatedAt: '2026-01-01T00:00:00Z',
  },
];
vi.mock('@/hooks/use-contact-segments', () => ({
  useContactSegments: () => ({
    segments: SEGMENTS,
    create: vi.fn(),
    update: vi.fn(),
    remove: vi.fn(),
  }),
}));
vi.mock('@/hooks/use-contact-tags', () => ({ useContactTags: () => ({ tags: [] }) }));
vi.mock('@/hooks/use-contact-fields', () => ({ useContactFields: () => ({ fields: [] }) }));
vi.mock('@/hooks/use-contact-lifecycle-stages', () => ({
  useContactLifecycleStages: () => ({ stages: [] }),
}));
vi.mock('@/hooks/use-workspace-members', () => ({ useWorkspaceMembers: () => ({ members: [] }) }));
vi.mock('@/hooks/use-contact-bulk', () => ({
  useContactBulk: () => ({ busy: false, assign: vi.fn(), tags: vi.fn(), lifecycle: vi.fn() }),
  reportBulkResult: vi.fn(),
}));
vi.mock('@/services/channel-service', () => ({
  channelService: { listByWorkspace: vi.fn().mockResolvedValue([]) },
}));
vi.mock('@/components/platform/resource-list', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/components/platform/resource-list')>();
  return { ...actual, ResourceList: () => <div data-testid="resource-list" /> };
});

describe('ContactsPage - segments.manage gating', () => {
  it('hides "Manage segments" for a user without segments.manage, even with saved segments present', async () => {
    permissions = new Set(['contacts.read']);
    render(<ContactsPage />);
    await waitFor(() => expect(screen.getByTestId('resource-list')).toBeInTheDocument());
    expect(screen.queryByRole('button', { name: 'Manage segments' })).not.toBeInTheDocument();
  });

  it('shows "Manage segments" once segments.manage is granted', async () => {
    permissions = new Set(['contacts.read', 'segments.manage']);
    render(<ContactsPage />);
    expect(await screen.findByRole('button', { name: 'Manage segments' })).toBeInTheDocument();
  });
});
