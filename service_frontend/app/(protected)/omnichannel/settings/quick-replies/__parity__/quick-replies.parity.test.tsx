/**
 * Switch-off parity for the Quick replies page (Foundryx UIUX slice W2-WS):
 * the list and the new / edit dialog, rendered with the switch OFF. Recorded
 * on the code as it was before the slice; a change that needs one of these
 * snapshots updated is wrong by definition (fix the code, never the
 * snapshot).
 */
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { parityHtml } from '@/components/fx/__parity__/parity-utils';
import { SettingsProvider } from '@/providers/settings-provider';
import type { QuickReply } from '@/types/omnichannel';
import QuickRepliesPage from '../page';
import { QuickReplyDialog } from '../quick-reply-dialog';

vi.mock('next/navigation', () => ({
  useRouter: vi.fn(() => ({ push: vi.fn(), prefetch: vi.fn(), replace: vi.fn(), back: vi.fn() })),
  useSearchParams: vi.fn(() => new URLSearchParams()),
  usePathname: vi.fn(() => '/omnichannel/settings/quick-replies'),
}));
vi.mock('next-auth/react', () => ({
  useSession: () => ({ data: { user: { name: 'Demo Admin', permissions: [] } }, status: 'authenticated' }),
}));
vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({ can: () => true, ready: true, permissions: new Set<string>() }),
}));
vi.mock('@/components/common/require-permission', () => ({
  RequirePermission: ({ children }: { children: React.ReactNode }) => children,
}));
vi.mock('@/lib/impersonation-store', () => ({ useImpersonationSession: () => null }));
vi.mock('@/services/preferences-service', () => ({
  preferencesService: { get: vi.fn().mockResolvedValue(null), save: vi.fn().mockResolvedValue(undefined) },
}));
vi.mock('@/services/terminology-service', () => ({
  terminologyService: { getTerminology: vi.fn().mockResolvedValue({}) },
}));
vi.mock('@/providers/import-activity-provider', () => ({
  useImportActivity: () => ({ openImport: vi.fn() }),
}));
vi.mock('@/services/pending-actions-service', () => ({
  pendingActionsService: { park: vi.fn(), cancel: vi.fn(), current: vi.fn().mockResolvedValue({ pending: null }) },
}));

const ITEMS: QuickReply[] = [
  { id: 'qr-1', workspaceId: 'wsp-1', shortcut: '/greeting', body: 'Hi! Thanks for reaching out.' },
  { id: 'qr-2', workspaceId: 'wsp-1', shortcut: null, body: 'We will get back to you within one working day.' },
];
vi.mock('@/services/workspace-service', () => ({
  workspaceService: {
    list: vi.fn(async () => ({
      data: [{ id: 'wsp-1', name: 'General', isDefault: true }],
      total: 1,
      page: 0,
    })),
  },
}));
vi.mock('@/services/quick-reply-service', () => ({
  quickReplyService: {
    list: vi.fn(async () => ITEMS),
    create: vi.fn(),
    update: vi.fn(),
    remove: vi.fn(),
  },
}));

function stable(root: Element): string {
  const seen = new Map<string, string>();
  return parityHtml(root).replace(/_r_[0-9a-z]+_/g, (id) => {
    let name = seen.get(id);
    if (!name) {
      name = `_rid${seen.size}_`;
      seen.set(id, name);
    }
    return name;
  });
}

describe('parity (switch off): Quick replies', () => {
  it('list with rows', async () => {
    const { container } = render(
      <SettingsProvider>
        <QuickRepliesPage />
      </SettingsProvider>,
    );
    await screen.findByText('/greeting');
    expect(stable(container)).toMatchSnapshot();
  });

  it('new dialog', () => {
    render(<QuickReplyDialog item={null} onClose={vi.fn()} onCreate={vi.fn()} onUpdate={vi.fn()} />);
    expect(stable(document.body)).toMatchSnapshot();
  });

  it('edit dialog', () => {
    render(<QuickReplyDialog item={ITEMS[0]} onClose={vi.fn()} onCreate={vi.fn()} onUpdate={vi.fn()} />);
    expect(stable(document.body)).toMatchSnapshot();
  });
});
