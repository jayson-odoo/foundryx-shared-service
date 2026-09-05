/** AC-IVE-39/43/48 - hidden when the shortcut list is empty OR the caller
 *  lacks `conversations.shortcut` (foolproof-UI); a 409 (unauthorized Code
 *  node) surfaces the server's own message, not a generic one. */
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { toast } from '@/lib/toast';
import { ApiError } from '@/lib/api-client';
import { ShortcutMenu } from './shortcut-menu';

const { useSessionMock } = vi.hoisted(() => ({ useSessionMock: vi.fn() }));
vi.mock('next-auth/react', () => ({ useSession: useSessionMock }));
vi.mock('@/lib/impersonation-store', () => ({ useImpersonationSession: () => null }));

const { pushMock } = vi.hoisted(() => ({ pushMock: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push: pushMock }) }));

const { listShortcutsMock, runShortcutMock } = vi.hoisted(() => ({
  listShortcutsMock: vi.fn(),
  runShortcutMock: vi.fn(),
}));
vi.mock('@/services/conversation-service', () => ({
  conversationService: { listShortcuts: listShortcutsMock, runShortcut: runShortcutMock },
}));

vi.mock('@/lib/toast', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

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

  it('running a shortcut toasts success with a link to the run (AC-IVE-39)', async () => {
    withPermissions(['conversations.shortcut', 'workflows.read']);
    listShortcutsMock.mockResolvedValue([{ workflowId: 'wf-1', name: 'Send NPS survey' }]);
    runShortcutMock.mockResolvedValue({ runId: 'run-1', status: 'PENDING' });
    const user = userEvent.setup();
    render(<ShortcutMenu contactId="cnt-001" />);

    await user.click(await screen.findByRole('combobox', { name: 'Run a shortcut' }));
    await user.click(await screen.findByText('Send NPS survey'));

    await waitFor(() => expect(runShortcutMock).toHaveBeenCalledWith('cnt-001', 'wf-1'));
    await waitFor(() => expect(toast.success).toHaveBeenCalled());
    expect(toast.error).not.toHaveBeenCalled();

    const [, options] = (toast.success as ReturnType<typeof vi.fn>).mock.calls.at(-1)!;
    expect(options.action?.label).toBe('View run');
    options.action.onClick();
    expect(pushMock).toHaveBeenCalledWith('/workflows/wf-1?edit=1&debug=run-1');
  });

  it('running a shortcut without workflows.read toasts success with NO link (foolproof-UI)', async () => {
    withPermissions(['conversations.shortcut']);
    listShortcutsMock.mockResolvedValue([{ workflowId: 'wf-1', name: 'Send NPS survey' }]);
    runShortcutMock.mockResolvedValue({ runId: 'run-1', status: 'PENDING' });
    const user = userEvent.setup();
    render(<ShortcutMenu contactId="cnt-001" />);

    await user.click(await screen.findByRole('combobox', { name: 'Run a shortcut' }));
    await user.click(await screen.findByText('Send NPS survey'));

    await waitFor(() => expect(toast.success).toHaveBeenCalled());
    const [, options] = (toast.success as ReturnType<typeof vi.fn>).mock.calls.at(-1)!;
    expect(options.action).toBeUndefined();
  });

  it('a 409 (unauthorized Code node) toasts the SERVER message, not a generic one (AC-IVE-39/48)', async () => {
    withPermissions(['conversations.shortcut']);
    listShortcutsMock.mockResolvedValue([{ workflowId: 'wf-1', name: 'Send NPS survey' }]);
    runShortcutMock.mockRejectedValue(
      new ApiError("This workflow's published version has an unauthorized Code node.", 409),
    );
    const user = userEvent.setup();
    render(<ShortcutMenu contactId="cnt-001" />);

    await user.click(await screen.findByRole('combobox', { name: 'Run a shortcut' }));
    await user.click(await screen.findByText('Send NPS survey'));

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        "This workflow's published version has an unauthorized Code node.",
      ),
    );
  });
});
