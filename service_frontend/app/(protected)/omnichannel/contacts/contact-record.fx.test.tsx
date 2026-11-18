/**
 * Contact record and new-contact page with the Foundryx UIUX switch on
 * (slice W1-CONTACT): the Details / Conversation toggle keeping each side,
 * the record arrows, identical requests in both looks, the done toasts (Undo
 * for tags and details, none for a lifecycle move), the typed erase confirm
 * through the contacts list's action, Hold to Copy on values, and the red
 * action of the new-contact page. The switch-off pages are pinned by
 * `__parity__/contact-record.parity.test.tsx`.
 */
import type { ReactNode } from 'react';
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type {
  ConversationThread,
  PatchContactInput,
} from '@/types/omnichannel';
import { FX_DEFAULT_THEME } from '@/lib/fx/cookies';
import { FxProvider } from '@/providers/fx-provider';
import { SettingsProvider } from '@/providers/settings-provider';
import {
  resetPageActionsForTests,
  usePageActions,
} from '@/components/fx/actions/page-actions-context';
import { ContactDetailsForm } from '@/components/platform/conversation-drawer/contact-details-form';
import { TagChips } from '@/components/platform/conversation-drawer/tag-chips';
import {
  FIELDS,
  LIST_CTX,
  MOVES,
  RECORD_ID,
  recordItem,
  recordThread,
  STAGES,
  TAGS,
} from './__parity__/contact-record-fixtures';
import { ContactFormView } from './components/contact-form-view';
import {
  contactDetailsUndoPatch,
  contactInitials,
  newContactName,
} from './components/contact-record-fx';
import { FxContactPanel } from './components/fx-contact-panel';

const h = vi.hoisted(() => ({
  toastCalls: [] as unknown[][],
  push: vi.fn(),
  pathname: '/omnichannel/contacts/cnt-001',
  search: '',
  permissions: new Set<string>(),
  get: vi.fn(),
  getAt: vi.fn(),
  create: vi.fn(),
  erase: vi.fn(),
  messages: null as unknown,
}));

vi.mock('@/lib/toast', () => {
  const rec =
    (kind: string) =>
    (...args: unknown[]) => {
      h.toastCalls.push([kind, ...args]);
      return 'toast-id';
    };
  return {
    toast: {
      success: rec('success'),
      error: rec('error'),
      info: rec('info'),
      warning: rec('warning'),
      message: rec('message'),
      custom: rec('custom'),
      dismiss: rec('dismiss'),
      fxDone: rec('fxDone'),
    },
  };
});
vi.mock('next/navigation', () => ({
  useRouter: () => ({
    push: h.push,
    replace: vi.fn(),
    prefetch: vi.fn(),
    back: vi.fn(),
  }),
  usePathname: () => h.pathname,
  useSearchParams: () => new URLSearchParams(h.search),
  useParams: () => ({ id: RECORD_ID }),
}));
vi.mock('next-auth/react', async () => {
  const { createContext } = await import('react');
  const session = {
    data: { user: { name: 'Kay', permissions: [] } },
    status: 'authenticated',
  };
  return { useSession: () => session, SessionContext: createContext(session) };
});
vi.mock('@/lib/impersonation-store', () => ({
  useImpersonationSession: () => null,
}));
vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({
    can: (key: string) => h.permissions.has(key),
    ready: true,
    permissions: h.permissions,
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
vi.mock('@/hooks/use-contact-fields', () => ({
  useContactFields: () => ({
    fields: FIELDS,
    loading: false,
    refetch: vi.fn(),
  }),
}));
vi.mock('@/hooks/use-contact-tags', () => ({
  useContactTags: () => ({ tags: TAGS, loading: false, refetch: vi.fn() }),
}));
vi.mock('@/hooks/use-contact-lifecycle-stages', () => ({
  useContactLifecycleStages: () => ({ stages: STAGES, loading: false }),
}));
vi.mock('@/hooks/use-lifecycle-moves', () => ({
  useLifecycleMoves: () => ({ moves: MOVES, loading: false, refetch: vi.fn() }),
}));
vi.mock('@/hooks/use-messages', () => ({
  useMessages: () => h.messages,
}));
vi.mock('@/services/contact-service', () => ({
  contactService: {
    get: (...a: unknown[]) => h.get(...a),
    getAt: (...a: unknown[]) => h.getAt(...a),
    create: (...a: unknown[]) => h.create(...a),
    eraseContact: (...a: unknown[]) => h.erase(...a),
  },
}));
// Pickers as plain selects, the same in both looks, so a test can choose an
// option without driving a popover.
vi.mock('@/components/platform/search-select', () => ({
  SearchSelect: ({
    options,
    value,
    onChange,
    ariaLabel,
    disabled,
  }: {
    options: { label: string; value: string }[];
    value: string | null;
    onChange: (v: string) => void;
    ariaLabel?: string;
    disabled?: boolean;
  }) => (
    <select
      aria-label={ariaLabel}
      value={value ?? ''}
      disabled={disabled}
      onChange={(e) => onChange(e.target.value)}
    >
      <option value="">-</option>
      {options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  ),
}));
// The conversation pane has its own tests (PR #292); here a stub with its
// own typed state shows whether switching sides keeps it.
vi.mock('@/components/platform/conversation-drawer', async (importOriginal) => {
  const actual =
    await importOriginal<
      typeof import('@/components/platform/conversation-drawer')
    >();
  return {
    ...actual,
    ConversationDrawer: ({
      contactId,
      compact,
    }: {
      contactId: string;
      compact?: boolean;
    }) => (
      <div
        data-stub="conversation-pane"
        data-contact={contactId}
        data-compact={String(Boolean(compact))}
      >
        <input aria-label="Reply draft" defaultValue="" />
      </div>
    ),
  };
});

function Fx({ children }: { children: ReactNode }) {
  return (
    <FxProvider initial initialTheme={FX_DEFAULT_THEME}>
      <SettingsProvider>{children}</SettingsProvider>
    </FxProvider>
  );
}
function Off({ children }: { children: ReactNode }) {
  return (
    <FxProvider initial={false} initialTheme={FX_DEFAULT_THEME}>
      <SettingsProvider>{children}</SettingsProvider>
    </FxProvider>
  );
}

let mainLabel: {
  label: string;
  fullLabel?: string;
  onClick?: () => void;
} | null = null;
function HeaderProbe() {
  const page = usePageActions();
  mainLabel = page.main;
  return <span data-testid="main-action">{page.main?.label ?? ''}</span>;
}

function messagesFor(thread: ConversationThread = recordThread()) {
  const state = { thread };
  return {
    get thread() {
      return state.thread;
    },
    isLoading: false,
    error: null,
    patchContact: vi.fn(async (patch: PatchContactInput) => {
      if (patch.tagIds) {
        state.thread = {
          ...state.thread,
          tags: patch.tagIds.map((id) => {
            const t = TAGS.find((x) => x.id === id)!;
            return { id: t.id, name: t.name, emoji: t.emoji, color: t.color };
          }),
        };
      }
      return state.thread;
    }),
    moveLifecycle: vi.fn(async () => ({
      ...state.thread,
      lifecycle: {
        ...state.thread.lifecycle!,
        key: 'lead',
        label: 'Lead',
        statusId: 'st-lead',
      },
    })),
  };
}

type Messages = ReturnType<typeof messagesFor>;
const msgs = () => h.messages as Messages;
const fxDoneCalls = () =>
  h.toastCalls
    .filter((c) => c[0] === 'fxDone')
    .map((c) => c[1] as Record<string, unknown>);

beforeEach(() => {
  h.toastCalls.length = 0;
  h.push.mockReset();
  h.pathname = `/omnichannel/contacts/${RECORD_ID}`;
  h.search = '';
  h.permissions = new Set([
    'contacts.read',
    'contacts.manage',
    'contacts.erase',
  ]);
  h.get.mockReset().mockResolvedValue(recordItem());
  h.getAt
    .mockReset()
    .mockImplementation(async (_ws: string, _q: unknown, index: number) => ({
      contact: { id: `cnt-${index}` },
      total: 137,
    }));
  h.create.mockReset().mockResolvedValue({ id: 'cnt-new' });
  h.erase.mockReset().mockResolvedValue({
    contactId: RECORD_ID,
    erasedAt: '',
    messages: 12,
    files: 2,
  });
  h.messages = messagesFor();
  mainLabel = null;
  resetPageActionsForTests();
});
afterEach(() => resetPageActionsForTests());

async function renderRecord() {
  const view = render(
    <Fx>
      <HeaderProbe />
      <ContactFormView contactId={RECORD_ID} workspaceId="wsp-1" />
    </Fx>,
  );
  await screen.findByRole('heading', { level: 1 });
  await screen.findByTestId('fx-contact-panel');
  return view;
}

function toggleTo(name: 'Details' | 'Conversation') {
  const item = within(screen.getByTestId('fx-record-toggle')).getByRole(
    'radio',
    { name },
  );
  fireEvent.click(item);
}

describe('record header', () => {
  it('names the contact with initials, the phone under it, and no red action', async () => {
    await renderRecord();
    const h1 = screen.getByRole('heading', { level: 1 });
    expect(h1).toHaveTextContent('AR');
    expect(h1).toHaveTextContent('Aisyah binti Rahman');
    // The phone sits under the name (and again in Details).
    expect(screen.getAllByText('+60123456789').length).toBeGreaterThanOrEqual(
      2,
    );
    // Once in the header and once above it for phones (one shows per width).
    const backLinks = screen.getAllByRole('link', { name: 'Back to contacts' });
    expect(backLinks).toHaveLength(2);
    for (const link of backLinks)
      expect(link).toHaveAttribute(
        'href',
        expect.stringContaining('/omnichannel/contacts'),
      );
    // Per-section editing stays (Q-EDIT): the mock shows no red action here.
    expect(screen.getByTestId('main-action')).toHaveTextContent('');
    expect(contactInitials('Aisyah binti Rahman')).toBe('AR');
    expect(contactInitials('Kay')).toBe('K');
    expect(contactInitials('Check Contact 17')).toBe('CC');
  });
});

describe('Details / Conversation toggle', () => {
  it('slides between the sides and keeps what each side held', async () => {
    await renderRecord();
    expect(screen.queryByLabelText('Reply draft')).toBeNull();

    // Details side: start an edit and type.
    fireEvent.click(screen.getByTestId('contact-details-edit'));
    fireEvent.change(screen.getByLabelText('First name'), {
      target: { value: 'Aisyah Nur' },
    });

    toggleTo('Conversation');
    const pane = await screen.findByLabelText('Reply draft');
    expect(pane.closest('[data-stub]')).toHaveAttribute('data-compact', 'true');
    expect(document.querySelector('[data-fx-side="details"]')).toHaveAttribute(
      'hidden',
    );
    fireEvent.change(pane, { target: { value: 'Half a reply' } });

    toggleTo('Details');
    expect(
      document.querySelector('[data-fx-side="conversation"]'),
    ).toHaveAttribute('hidden');
    // The Details edit is still open with what was typed.
    expect(screen.getByLabelText('First name')).toHaveValue('Aisyah Nur');

    toggleTo('Conversation');
    expect(screen.getByLabelText('Reply draft')).toHaveValue('Half a reply');
  });
});

describe('record arrows', () => {
  it('"3 of 137" between the arrows', async () => {
    h.search = `ctx=${LIST_CTX}&i=2`;
    await renderRecord();
    await screen.findByText('3 of 137');
    expect(
      screen.getByRole('button', { name: 'Previous record' }),
    ).not.toHaveAttribute('aria-disabled');
    expect(
      screen.getByRole('button', { name: 'Next record' }),
    ).not.toHaveAttribute('aria-disabled');
  });

  it('greys Previous on the first record and Next on the last', async () => {
    h.search = `ctx=${LIST_CTX}&i=0`;
    const first = await renderRecord();
    await screen.findByText('1 of 137');
    expect(
      screen.getByRole('button', { name: 'Previous record' }),
    ).toHaveAttribute('aria-disabled', 'true');
    expect(
      screen.getByRole('button', { name: 'Next record' }),
    ).not.toHaveAttribute('aria-disabled');
    first.unmount();

    h.search = `ctx=${LIST_CTX}&i=136`;
    await renderRecord();
    await screen.findByText('137 of 137');
    expect(screen.getByRole('button', { name: 'Next record' })).toHaveAttribute(
      'aria-disabled',
      'true',
    );
    expect(
      screen.getByRole('button', { name: 'Previous record' }),
    ).not.toHaveAttribute('aria-disabled');
  });

  it('hide while Details is being edited', async () => {
    h.search = `ctx=${LIST_CTX}&i=2`;
    await renderRecord();
    await screen.findByText('3 of 137');
    fireEvent.click(screen.getByTestId('contact-details-edit'));
    await waitFor(() => expect(screen.queryByText('3 of 137')).toBeNull());
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    await screen.findByText('3 of 137');
  });
});

describe('identical requests in both looks', () => {
  async function detailsEdit(look: 'off' | 'on'): Promise<unknown[]> {
    const onSave = vi.fn(async (patch: PatchContactInput) => {
      void patch;
      return recordThread();
    });
    const thread = recordThread();
    const Wrap = look === 'on' ? Fx : Off;
    const view = render(
      <Wrap>
        {look === 'on' ? (
          <FxContactPanel
            thread={thread}
            onPatchContact={onSave}
            onMoveLifecycle={vi.fn()}
          />
        ) : (
          <ContactDetailsForm thread={thread} fields={FIELDS} onSave={onSave} />
        )}
      </Wrap>,
    );
    fireEvent.click(screen.getByTestId('contact-details-edit'));
    fireEvent.change(screen.getByLabelText('First name'), {
      target: { value: 'Aisyah Nur' },
    });
    fireEvent.change(screen.getByLabelText('Email'), { target: { value: '' } });
    fireEvent.change(screen.getByLabelText('Country'), {
      target: { value: 'sg' },
    });
    fireEvent.change(screen.getByLabelText('Company'), {
      target: { value: 'Mawar Florist' },
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId('contact-details-save'));
    });
    await waitFor(() => expect(onSave).toHaveBeenCalled());
    view.unmount();
    return onSave.mock.calls;
  }

  it('a details edit sends the same PATCH', async () => {
    const off = await detailsEdit('off');
    const on = await detailsEdit('on');
    expect(off).toEqual([
      [
        {
          firstName: 'Aisyah Nur',
          email: null,
          countryCode: 'SG',
          customFields: { company: 'Mawar Florist' },
        },
      ],
    ]);
    expect(on).toEqual(off);
  });

  async function tagChange(
    look: 'off' | 'on',
    change: 'add' | 'remove',
  ): Promise<unknown[]> {
    const onPatch = vi.fn(async (patch: PatchContactInput) => {
      void patch;
      return recordThread();
    });
    const thread = recordThread();
    const Wrap = look === 'on' ? Fx : Off;
    const view = render(
      <Wrap>
        {look === 'on' ? (
          <FxContactPanel
            thread={thread}
            onPatchContact={onPatch}
            onMoveLifecycle={vi.fn()}
          />
        ) : (
          <TagChips
            tags={thread.tags}
            workspaceTags={TAGS}
            onChange={(tagIds) => onPatch({ tagIds })}
          />
        )}
      </Wrap>,
    );
    await act(async () => {
      if (change === 'add')
        fireEvent.change(screen.getByLabelText('Add tag'), {
          target: { value: 'tag-2' },
        });
      else fireEvent.click(screen.getByRole('button', { name: 'Remove VIP' }));
    });
    await waitFor(() => expect(onPatch).toHaveBeenCalled());
    view.unmount();
    return onPatch.mock.calls;
  }

  it('a tag change sends the same PATCH', async () => {
    const addOff = await tagChange('off', 'add');
    const addOn = await tagChange('on', 'add');
    expect(addOff).toEqual([[{ tagIds: ['tag-1', 'tag-2'] }]]);
    expect(addOn).toEqual(addOff);
    const removeOff = await tagChange('off', 'remove');
    const removeOn = await tagChange('on', 'remove');
    expect(removeOff).toEqual([[{ tagIds: [] }]]);
    expect(removeOn).toEqual(removeOff);
  });

  async function createContact(look: 'off' | 'on'): Promise<unknown[]> {
    h.pathname = '/omnichannel/contacts/new';
    h.create.mockClear();
    resetPageActionsForTests();
    const Wrap = look === 'on' ? Fx : Off;
    const view = render(
      <Wrap>
        <HeaderProbe />
        <ContactFormView workspaceId="wsp-1" />
      </Wrap>,
    );
    await screen.findByRole('heading', { level: 1 });
    fireEvent.change(screen.getByLabelText('First name'), {
      target: { value: 'Aisyah' },
    });
    fireEvent.change(screen.getByLabelText('Last name'), {
      target: { value: 'binti Rahman' },
    });
    fireEvent.change(screen.getByLabelText('Phone *'), {
      target: { value: '+60123456789' },
    });
    fireEvent.change(screen.getByLabelText('Email'), {
      target: { value: 'aisyah@example.com' },
    });
    fireEvent.change(screen.getByLabelText('Company'), {
      target: { value: 'Kedai' },
    });
    await act(async () => {
      if (look === 'off')
        fireEvent.click(screen.getByRole('button', { name: 'Create contact' }));
      else
        screen
          .getByRole('button', { name: /Create Aisyah binti Rahman/ })
          .click();
    });
    await waitFor(() => expect(h.create).toHaveBeenCalled());
    view.unmount();
    return h.create.mock.calls;
  }

  it('a new contact sends the same create request', async () => {
    const off = await createContact('off');
    const on = await createContact('on');
    expect(off).toEqual([
      [
        'wsp-1',
        {
          firstName: 'Aisyah',
          lastName: 'binti Rahman',
          phone: '+60123456789',
          email: 'aisyah@example.com',
          language: null,
          countryCode: null,
          lifecycleStatusId: 'st-lead',
          tagIds: [],
          customFields: { company: 'Kedai' },
        },
      ],
    ]);
    expect(on).toEqual(off);
  });
});

describe('done toasts', () => {
  it('a tag change says so, and Undo puts it back through the same PATCH', async () => {
    await renderRecord();
    await act(async () => {
      fireEvent.change(screen.getByLabelText('Add tag'), {
        target: { value: 'tag-2' },
      });
    });
    await waitFor(() => expect(fxDoneCalls()).toHaveLength(1));
    const done = fxDoneCalls()[0];
    expect(done).toMatchObject({
      what: 'Tag "Florist" added to Aisyah binti Rahman',
      byWhom: 'Kay',
      seconds: 5,
    });
    expect(typeof done.undo).toBe('function');

    await act(async () => {
      (done.undo as () => void)();
    });
    expect(msgs().patchContact).toHaveBeenLastCalledWith({ tagIds: ['tag-1'] });
    await waitFor(() => expect(fxDoneCalls()).toHaveLength(2));
    expect(fxDoneCalls()[1]).toMatchObject({
      what: 'Tag "Florist" removed from Aisyah binti Rahman',
    });
  });

  it('removing a tag: Undo adds it back', async () => {
    await renderRecord();
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Remove VIP' }));
    });
    await waitFor(() => expect(fxDoneCalls()).toHaveLength(1));
    expect(fxDoneCalls()[0]).toMatchObject({
      what: 'Tag "VIP" removed from Aisyah binti Rahman',
    });
    await act(async () => {
      (fxDoneCalls()[0].undo as () => void)();
    });
    expect(msgs().patchContact).toHaveBeenLastCalledWith({ tagIds: ['tag-1'] });
  });

  it('a lifecycle move says so, with no Undo', async () => {
    await renderRecord();
    await act(async () => {
      fireEvent.change(screen.getByLabelText('Move to'), {
        target: { value: 'st-lead' },
      });
    });
    expect(msgs().moveLifecycle).toHaveBeenCalledWith('st-lead');
    await waitFor(() => expect(fxDoneCalls()).toHaveLength(1));
    expect(fxDoneCalls()[0]).toEqual({
      what: 'Aisyah binti Rahman moved to Lead',
      byWhom: 'Kay',
    });
    expect(fxDoneCalls()[0].undo).toBeUndefined();
  });

  it('a details save says so, and Undo PATCHes the old values back', async () => {
    await renderRecord();
    fireEvent.click(screen.getByTestId('contact-details-edit'));
    fireEvent.change(screen.getByLabelText('First name'), {
      target: { value: 'Aisyah Nur' },
    });
    fireEvent.change(screen.getByLabelText('Company'), {
      target: { value: 'Mawar' },
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId('contact-details-save'));
    });
    await waitFor(() => expect(fxDoneCalls()).toHaveLength(1));
    expect(fxDoneCalls()[0]).toMatchObject({
      what: "Aisyah binti Rahman's details updated",
      seconds: 5,
    });
    await act(async () => {
      (fxDoneCalls()[0].undo as () => void)();
    });
    expect(msgs().patchContact).toHaveBeenLastCalledWith({
      firstName: 'Aisyah',
      customFields: { company: 'Kedai Bunga Mawar' },
    });
  });

  it('the undo PATCH sends null for a value that was empty', () => {
    const baseline = {
      system: {
        firstName: '',
        lastName: 'X',
        email: 'a@b.c',
        language: '',
        countryCode: '',
      },
      custom: { company: null },
    };
    expect(
      contactDetailsUndoPatch(
        { firstName: 'A', email: null, customFields: { company: 'Y' } },
        baseline,
      ),
    ).toEqual({
      firstName: null,
      email: 'a@b.c',
      customFields: { company: null },
    });
  });
});

describe('view-only', () => {
  it('without contacts.manage: plain values, no pencil, no Move to, no tag changes', async () => {
    h.permissions = new Set(['contacts.read']);
    await renderRecord();
    expect(screen.queryByTestId('contact-details-edit')).toBeNull();
    expect(screen.queryByLabelText('Move to')).toBeNull();
    expect(screen.queryByLabelText('Add tag')).toBeNull();
    expect(screen.queryByRole('button', { name: 'Remove VIP' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'More' })).toBeNull();
    expect(screen.getByText('aisyah@example.com')).toBeInTheDocument();
  });
});

describe('erase', () => {
  it('More holds Erase contact; its typed confirm runs the contacts list action', async () => {
    h.search = `ctx=${LIST_CTX}&i=2`;
    await renderRecord();
    const more = screen.getByRole('button', { name: 'More' });
    fireEvent.pointerDown(more, { button: 0, pointerType: 'mouse' });
    fireEvent.click(more);
    fireEvent.click(
      await screen.findByRole('menuitem', { name: /Erase contact/ }),
    );

    const dialog = await screen.findByRole('alertdialog');
    expect(
      within(dialog).getByText('Erase Aisyah binti Rahman?'),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByRole('button', { name: 'Keep contact' }),
    ).toBeInTheDocument();
    const erase = within(dialog).getByRole('button', { name: 'Erase contact' });
    const input = within(dialog).getByLabelText('Type "Aisyah binti Rahman"');
    fireEvent.change(input, { target: { value: 'ERASE' } });
    fireEvent.click(erase);
    expect(h.erase).not.toHaveBeenCalled();

    fireEvent.change(input, { target: { value: 'aisyah binti rahman' } });
    await act(async () => {
      fireEvent.click(erase);
    });
    await waitFor(() => expect(h.erase).toHaveBeenCalledWith(RECORD_ID));
    await waitFor(() => expect(h.push).toHaveBeenCalled());
    // Back to the list, keeping its place.
    expect(h.push.mock.calls[0][0]).toContain(`ctx=${LIST_CTX}`);
    expect(h.push.mock.calls[0][0]).toContain(`from=${RECORD_ID}`);
    expect(fxDoneCalls()[0]).toMatchObject({
      what: 'Aisyah binti Rahman erased',
      howMany: 'with 12 messages and 2 files',
      byWhom: 'Kay',
    });
    expect(fxDoneCalls()[0].undo).toBeUndefined();
  });

  it('no More menu without contacts.erase', async () => {
    h.permissions = new Set(['contacts.read', 'contacts.manage']);
    await renderRecord();
    expect(screen.queryByRole('button', { name: 'More' })).toBeNull();
  });
});

describe('Hold to Copy', () => {
  it('wraps the name, phone and email values', async () => {
    await renderRecord();
    const copyable = Array.from(document.querySelectorAll('[data-fx-h2c]')).map(
      (el) => el.textContent,
    );
    expect(copyable).toEqual(
      expect.arrayContaining([
        'Aisyah binti Rahman',
        '+60123456789',
        'aisyah@example.com',
        'Aisyah',
        'binti Rahman',
      ]),
    );
  });

  it('holding the phone copies it', async () => {
    const writeText = vi.fn(async (text: string) => {
      void text;
    });
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText },
    });
    await renderRecord();
    const phone = Array.from(
      document.querySelectorAll<HTMLElement>('[data-fx-h2c]'),
    ).find((el) => el.textContent === '+60123456789')!;
    vi.useFakeTimers();
    try {
      fireEvent.pointerEnter(phone, {
        clientX: 20,
        clientY: 20,
        pointerType: 'mouse',
      });
      fireEvent.pointerDown(phone, {
        button: 0,
        clientX: 20,
        clientY: 20,
        pointerType: 'mouse',
      });
      act(() => {
        vi.advanceTimersByTime(800);
      });
      expect(writeText).toHaveBeenCalledWith('+60123456789');
    } finally {
      vi.useRealTimers();
    }
  });
});

describe('new contact', () => {
  beforeEach(() => {
    h.pathname = '/omnichannel/contacts/new';
  });

  it('Create contact is the red action and names the contact once typed', async () => {
    render(
      <Fx>
        <HeaderProbe />
        <ContactFormView workspaceId="wsp-1" />
      </Fx>,
    );
    await screen.findByRole('heading', { level: 1, name: 'New contact' });
    await waitFor(() =>
      expect(screen.getByTestId('main-action')).toHaveTextContent(
        'Create contact',
      ),
    );
    expect(mainLabel?.fullLabel).toBeUndefined();
    fireEvent.change(screen.getByLabelText('First name'), {
      target: { value: 'Aisyah' },
    });
    await waitFor(() => expect(mainLabel?.fullLabel).toBe('Create Aisyah'));
    // Never twice: no second create button on the page.
    expect(screen.getAllByRole('button', { name: /Create/ })).toHaveLength(1);
  });

  it('a missing phone shows its message and sends nothing; a create says who was added', async () => {
    render(
      <Fx>
        <HeaderProbe />
        <ContactFormView workspaceId="wsp-1" />
      </Fx>,
    );
    await screen.findByRole('heading', { level: 1, name: 'New contact' });
    await act(async () => {
      screen.getByRole('button', { name: 'Create contact' }).click();
    });
    expect(await screen.findByText('Phone is required.')).toHaveAttribute(
      'data-fx-message',
      'error',
    );
    expect(h.create).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText('Phone *'), {
      target: { value: '+60123456789' },
    });
    await act(async () => {
      screen.getByRole('button', { name: 'Create contact' }).click();
    });
    await waitFor(() =>
      expect(h.push).toHaveBeenCalledWith('/omnichannel/contacts/cnt-new'),
    );
    expect(fxDoneCalls()[0]).toEqual({
      what: '+60123456789 added',
      byWhom: 'Kay',
    });
    expect(
      newContactName({ firstName: ' Aisyah ', lastName: '', phone: '+6012' }),
    ).toBe('Aisyah');
  });

  it('Cancel with typed values asks once with a single-click Discard', async () => {
    render(
      <Fx>
        <ContactFormView workspaceId="wsp-1" />
      </Fx>,
    );
    await screen.findByRole('heading', { level: 1, name: 'New contact' });
    fireEvent.change(screen.getByLabelText('First name'), {
      target: { value: 'Aisyah' },
    });
    await waitFor(() =>
      expect(screen.getByLabelText('First name')).toHaveValue('Aisyah'),
    );
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    const dialog = await screen.findByRole('alertdialog');
    expect(
      within(dialog).getByText('Discard changes to Aisyah?'),
    ).toBeInTheDocument();
    expect(h.push).not.toHaveBeenCalled();
    fireEvent.click(
      within(dialog).getByRole('button', { name: 'Discard changes' }),
    );
    expect(h.push).toHaveBeenCalledWith('/omnichannel/contacts');
  });
});
