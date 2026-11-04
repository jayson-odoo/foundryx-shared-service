/**
 * Plan 56 C, AC-56-52 (+ the FE parts of AC-56-50/51) - the staff "Erase contact"
 * action. RED tests written BEFORE the implementation, matching mock v1
 * (documentation/mockups/SS-FUJI-READINESS/index.html).
 *
 * Seams the implementation must honour:
 * - ONE action definition in `use-contact-erase-action.tsx` (the file that holds the
 *   `confirm: { input }` block and the CARVE_OUTS row), used by BOTH the list registry
 *   (`useContactActions`, surface row) and the detail form (`useContactForm`, surface form).
 * - action id `erase-contact`, label `Erase contact`, tone destructive, permission
 *   `contacts.erase`, typed confirm `ERASE`.
 * - counts come from the row: `ContactListItem.messageCount` / `fileCount` (new fields on
 *   the list and get payloads, no extra request before the dialog).
 * - `contactService.eraseContact(contactId)` -> DELETE /omnichannel/contacts/{id}.
 */
import { act, render, renderHook, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ContactListItem } from '@/types/omnichannel';

const { eraseMock, getMock, pushMock, toastSuccess, toastError, canMock } = vi.hoisted(() => ({
  eraseMock: vi.fn(),
  getMock: vi.fn(),
  pushMock: vi.fn(),
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
  canMock: vi.fn(),
}));

vi.mock('@/services/contact-service', () => ({
  contactService: { eraseContact: eraseMock, get: getMock, getAt: vi.fn(), create: vi.fn() },
}));
vi.mock('@/lib/toast', () => ({ toast: { success: toastSuccess, error: toastError } }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push: pushMock }) }));
vi.mock('@/hooks/use-can', () => ({ useCan: () => ({ can: canMock }) }));
vi.mock('@/hooks/use-contact-fields', () => ({ useContactFields: () => ({ fields: [] }) }));
vi.mock('@/hooks/use-contact-tags', () => ({ useContactTags: () => ({ tags: [] }) }));
vi.mock('@/hooks/use-contact-lifecycle-stages', () => ({ useContactLifecycleStages: () => ({ stages: [] }) }));
vi.mock('@/components/platform/conversation-drawer', () => ({ ConversationDrawer: () => null }));
vi.mock('./contact-details-tab', () => ({ ContactDetailsTab: () => null }));

import { ActionMenu } from '@/components/platform/resource-actions/action-menu';
import { ApiError } from '@/lib/api-client';
import { useContactActions } from './use-contact-actions';
import { useContactForm } from './use-contact-form';

type Row = ContactListItem & { messageCount: number; fileCount: number };

function row(over: Partial<Row> = {}): Row {
  return {
    id: 'cnt-1', tenantId: 't1', workspaceId: 'wsp-1', name: 'Priya Raj', firstName: 'Priya', lastName: 'Raj',
    phone: '+60172020303', email: null, language: null, countryCode: null, avatarUrl: null,
    assignedUserId: null, assignedUserName: null, status: 'OPEN', priority: 'MEDIUM', channelId: null,
    channelType: 'WHATSAPP', cswExpiresAt: null, windowExpiresAt: null, humanAgentExpiresAt: null,
    lastIncomingMessageAt: null, lastMessageAt: null, lastMessagePreview: null, unreadCount: 0,
    customFields: {}, tags: [], lifecycle: null, createdAt: '2026-01-01T00:00:00Z', channels: [],
    messageCount: 14, fileCount: 4, ...over,
  } as Row;
}

const noop = () => {};
function registry() {
  return renderHook(() =>
    useContactActions({ onBulkAssign: noop, onAddTags: noop, onRemoveTags: noop, onMoveLifecycle: noop }),
  ).result.current;
}
const erase = () => registry().find((a) => a.id === 'erase-contact')!;

beforeEach(() => {
  vi.clearAllMocks();
  canMock.mockReturnValue(true);
});

describe('AC-56-52 list registry', () => {
  it('adds Erase contact as the LAST action, the existing four unchanged', () => {
    const ids = registry().map((a) => a.id);
    expect(ids).toEqual(['bulk-assign', 'add-tags', 'remove-tags', 'move-lifecycle', 'erase-contact']);
  });

  it('is destructive, gated contacts.erase and on the row surface ONLY (never bulk)', () => {
    const action = erase();
    expect(action.label).toBe('Erase contact');
    expect(action.tone).toBe('destructive');
    expect(action.permission).toBe('contacts.erase');
    expect(action.surfaces).toEqual({ row: true });
    expect('deferred' in action && action.deferred).toBeFalsy();
  });

  it('uses the typed confirm: ERASE, titled with the contact name, counts in the body', () => {
    const { confirm } = erase();
    const rows = [row()];
    const title = typeof confirm!.title === 'function' ? confirm!.title(rows) : confirm!.title;
    const desc = typeof confirm!.description === 'function' ? confirm!.description(rows) : confirm!.description;
    expect(title).toBe('Erase Priya Raj?');
    expect(desc).toBe('This erases the contact, 14 messages and 4 files. It cannot be undone.');
    const label =
      typeof confirm!.confirmLabel === 'function' ? confirm!.confirmLabel(rows) : confirm!.confirmLabel;
    expect(label).toBe('Erase contact');
    expect(confirm!.input!.expected(rows)).toBe('ERASE');
    expect(confirm!.input!.hint!(rows)).toBe('Type "ERASE" to confirm.');
  });

  it('singular counts read naturally', () => {
    const { confirm } = erase();
    const desc = (confirm!.description as (r: Row[]) => string)([row({ messageCount: 1, fileCount: 1 })]);
    expect(desc).toBe('This erases the contact, 1 message and 1 file. It cannot be undone.');
  });

  it('run erases through the service, toasts "Contact erased" and reloads the list', async () => {
    eraseMock.mockResolvedValue({ contactId: 'cnt-1', erasedAt: '2026-11-04T00:00:00Z', messages: 14, files: 4 });
    const reload = vi.fn();
    await erase().run!([row()], { reload, ctx: undefined, index: 0 });
    expect(eraseMock).toHaveBeenCalledWith('cnt-1');
    expect(toastSuccess).toHaveBeenCalledWith('Contact erased');
    expect(reload).toHaveBeenCalled();
  });

  it('a failed erase shows the error, reloads nothing and says nothing was erased', async () => {
    eraseMock.mockRejectedValue(new ApiError('Contact not found', 404));
    const reload = vi.fn();
    await erase().run!([row()], { reload, ctx: undefined, index: 0 });
    expect(toastError).toHaveBeenCalled();
    expect(toastSuccess).not.toHaveBeenCalled();
    expect(reload).not.toHaveBeenCalled();
  });
});

describe('AC-56-52 menu + typed confirm (real ActionMenu and ConfirmActionDialog)', () => {
  async function openMenu(user: ReturnType<typeof userEvent.setup>) {
    await user.click(screen.getByRole('button'));
  }

  it('hides Erase contact from users without contacts.erase (and shows it to those who have it)', async () => {
    const runtime = { reload: vi.fn(), ctx: undefined, index: 0 };
    canMock.mockImplementation((key: string) => key !== 'contacts.erase');
    const user = userEvent.setup();
    const first = render(<ActionMenu actions={registry()} rows={[row()]} runtime={runtime} surface="row" />);
    await openMenu(user);
    expect(await screen.findByText('Assign')).toBeTruthy();
    expect(screen.queryByText('Erase contact')).toBeNull();
    first.unmount();

    // control: the very same menu for a user holding the key shows the item
    canMock.mockReturnValue(true);
    render(<ActionMenu actions={registry()} rows={[row()]} runtime={runtime} surface="row" />);
    await openMenu(user);
    expect(await screen.findByText('Erase contact')).toBeTruthy();
  });

  it('keeps the confirm button disabled until ERASE is typed, then erases once', async () => {
    eraseMock.mockResolvedValue({ contactId: 'cnt-1', erasedAt: '2026-11-04T00:00:00Z', messages: 14, files: 4 });
    const reload = vi.fn();
    const user = userEvent.setup();
    render(
      <ActionMenu actions={registry()} rows={[row()]} runtime={{ reload, ctx: undefined, index: 0 }} surface="row" />,
    );
    await openMenu(user);
    await user.click(await screen.findByText('Erase contact'));

    const dialog = await screen.findByRole('alertdialog');
    expect(within(dialog).getByText('Erase Priya Raj?')).toBeTruthy();
    expect(within(dialog).getByText(/14 messages and 4 files/)).toBeTruthy();
    const confirmButton = within(dialog).getByRole('button', { name: 'Erase contact' });
    expect((confirmButton as HTMLButtonElement).disabled).toBe(true);

    const input = within(dialog).getByRole('textbox');
    await user.type(input, 'eras');
    expect((within(dialog).getByRole('button', { name: 'Erase contact' }) as HTMLButtonElement).disabled).toBe(true);
    await user.type(input, 'e');  // lower case is not ERASE
    expect((within(dialog).getByRole('button', { name: 'Erase contact' }) as HTMLButtonElement).disabled).toBe(true);
    await user.clear(input);
    await user.type(input, 'ERASE');
    const enabled = within(dialog).getByRole('button', { name: 'Erase contact' }) as HTMLButtonElement;
    expect(enabled.disabled).toBe(false);
    expect(eraseMock).not.toHaveBeenCalled(); // control: nothing happened before the confirm
    await user.click(enabled);
    await waitFor(() => expect(eraseMock).toHaveBeenCalledTimes(1));
    expect(eraseMock).toHaveBeenCalledWith('cnt-1');
    await waitFor(() => expect(toastSuccess).toHaveBeenCalledWith('Contact erased'));
  });
});

describe('AC-56-52 detail menu (same action from the same registry)', () => {
  it('lists Erase contact in the form actions on the form surface, gated contacts.erase', async () => {
    getMock.mockResolvedValue(row());
    const { result } = renderHook(() => useContactForm('cnt-1', 'wsp-1'));
    await waitFor(() => expect(result.current.config).not.toBeNull());
    const actions = result.current.config!.actions;
    expect(actions.map((a) => a.id)).toEqual(['erase-contact']);
    const action = actions[0];
    expect(action.tone).toBe('destructive');
    expect(action.permission).toBe('contacts.erase');
    expect(action.surfaces.form).toBe(true);
    expect(action.confirm?.input?.expected([row()])).toBe('ERASE');
    expect(result.current.config!.actionRows).toEqual([row()]);
  });

  it('has no erase action while creating a new contact', async () => {
    const { result } = renderHook(() => useContactForm(undefined, 'wsp-1'));
    await waitFor(() => expect(result.current.config).not.toBeNull());
    expect(result.current.config!.actions).toEqual([]);
  });

  it('after success: back to the contacts list, a "Contact erased" toast, no refetch of the erased record', async () => {
    getMock.mockResolvedValue(row());
    eraseMock.mockResolvedValue({ contactId: 'cnt-1', erasedAt: '2026-11-04T00:00:00Z', messages: 14, files: 4 });
    const { result } = renderHook(() => useContactForm('cnt-1', 'wsp-1'));
    await waitFor(() => expect(result.current.config).not.toBeNull());
    const reload = vi.fn();
    await act(async () => {
      await result.current.config!.actions[0].run!([row()], { reload, ctx: undefined, index: 0 });
    });
    expect(eraseMock).toHaveBeenCalledWith('cnt-1');
    expect(toastSuccess).toHaveBeenCalledWith('Contact erased');
    expect(pushMock).toHaveBeenCalledWith('/omnichannel/contacts');
    expect(reload).not.toHaveBeenCalled();
  });

  it('a failed erase stays on the detail view', async () => {
    getMock.mockResolvedValue(row());
    eraseMock.mockRejectedValue(new ApiError('Contact not found', 404));
    const { result } = renderHook(() => useContactForm('cnt-1', 'wsp-1'));
    await waitFor(() => expect(result.current.config).not.toBeNull());
    await act(async () => {
      await result.current.config!.actions[0].run!([row()], { reload: vi.fn(), ctx: undefined, index: 0 });
    });
    expect(toastError).toHaveBeenCalled();
    expect(pushMock).not.toHaveBeenCalled();
    expect(toastSuccess).not.toHaveBeenCalled();
  });
});
