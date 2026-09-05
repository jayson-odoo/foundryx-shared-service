/** AC-IVE-39/43/48 - hidden when the shortcut list is empty OR the caller
 *  lacks `conversations.shortcut` (foolproof-UI). */
import { render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { ShortcutMenu } from './shortcut-menu';

const { useSessionMock } = vi.hoisted(() => ({ useSessionMock: vi.fn() }));
vi.mock('next-auth/react', () => ({ useSession: useSessionMock }));
vi.mock('@/lib/impersonation-store', () => ({ useImpersonationSession: () => null }));

const { listShortcutsMock } = vi.hoisted(() => ({ listShortcutsMock: vi.fn() }));
vi.mock('@/services/conversation-service', () => ({
  conversationService: { listShortcuts: listShortcutsMock, runShortcut: vi.fn() },
}));

function withPermissions(perms: string[]) {
  useSessionMock.mockReturnValue({ status: 'authenticated', data: { user: { permissions: perms } } });
}

describe('ShortcutMenu', () => {
  it('renders nothing without conversations.shortcut, even with shortcuts available', async () => {
    withPermissions([]);
    listShortcutsMock.mockResolvedValue([{ workflowId: 'wf-1', name: 'Send NPS survey' }]);
    const { container } = render(<ShortcutMenu contactId="cnt-001" />);
    await waitFor(() => expect(listShortcutsMock).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it('renders nothing when the shortcut list is empty, even with the permission', async () => {
    withPermissions(['conversations.shortcut']);
    listShortcutsMock.mockResolvedValue([]);
    const { container } = render(<ShortcutMenu contactId="cnt-001" />);
    await waitFor(() => expect(listShortcutsMock).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it('renders the SearchSelect when both the permission and the list are present', async () => {
    withPermissions(['conversations.shortcut']);
    listShortcutsMock.mockResolvedValue([{ workflowId: 'wf-1', name: 'Send NPS survey' }]);
    render(<ShortcutMenu contactId="cnt-001" />);
    expect(await screen.findByRole('combobox', { name: 'Run a shortcut' })).toBeInTheDocument();
  });
});
