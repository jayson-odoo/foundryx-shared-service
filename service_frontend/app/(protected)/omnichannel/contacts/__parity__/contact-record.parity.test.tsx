/**
 * Switch-off parity for the contact record and the new-contact page
 * (Foundryx UIUX, slice W1-CONTACT). Recorded on the code BEFORE the slice
 * changed anything, so a later change that alters what a user sees or gets
 * with the switch off fails here. A change that needs one of these snapshots
 * updated is wrong by definition: fix the code, never the snapshot.
 *
 * Covers the page-local pieces the slice branches: the record view (header,
 * record card, record arrows, the Details tab with its three sections, the
 * Conversation tab's frame, the gear menu and the erase confirm), the
 * Details tab's loading and not-found states, and the new-contact form with
 * the request and toast a create sends.
 */
import type { ReactElement } from 'react';
import {
  act,
  fireEvent,
  render as rtlRender,
  screen,
  waitFor,
} from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { SettingsProvider } from '@/providers/settings-provider';
import { parityHtml as baseParityHtml } from '@/components/fx/__parity__/parity-utils';
import { ContactDetailsTab } from '../components/contact-details-tab';
import { ContactFormView } from '../components/contact-form-view';
import {
  FIELDS,
  LIST_CTX,
  MOVES,
  RECORD_ID,
  recordItem,
  recordThread,
  STAGES,
  TAGS,
} from './contact-record-fixtures';

/**
 * React 19's `_r_N_` ids renamed in order, so test order cannot shift them;
 * timing values and enter animations caught mid-way (opacity, scale)
 * masked.
 */
function parityHtml(root: Element): string {
  const seen = new Map<string, string>();
  return baseParityHtml(root)
    .replace(/_r_[0-9a-z]+_/g, (id) => {
      if (!seen.has(id)) seen.set(id, `_rid${seen.size}_`);
      return seen.get(id) as string;
    })
    .replace(
      /(animation|transition)-duration:\s*[0-9.]+m?s/g,
      '$1-duration: <t>',
    )
    .replace(/opacity:\s*[0-9.]+;/g, 'opacity: <o>;')
    .replace(/\s*scale\([0-9.]+\)/g, '');
}

const h = vi.hoisted(() => ({
  toastCalls: [] as unknown[],
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
vi.mock('next-auth/react', () => ({
  useSession: () => ({
    data: { user: { name: 'Kay', permissions: [] } },
    status: 'authenticated',
  }),
  SessionContext: undefined,
}));
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
      />
    ),
  };
});

function render(ui: ReactElement) {
  return rtlRender(<SettingsProvider>{ui}</SettingsProvider>);
}

function messagesFor(thread = recordThread()) {
  return {
    thread,
    isLoading: false,
    error: null,
    patchContact: vi.fn(async () => thread),
    moveLifecycle: vi.fn(async () => thread),
  };
}

beforeEach(() => {
  h.toastCalls = [];
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
});

async function renderRecord() {
  const view = render(
    <ContactFormView contactId={RECORD_ID} workspaceId="wsp-1" />,
  );
  await screen.findByRole('heading', { name: 'Aisyah binti Rahman' });
  return view;
}

describe('contact record, switch off (parity)', () => {
  it('record view: header, record card and Details tab', async () => {
    const { container } = await renderRecord();
    expect(parityHtml(container)).toMatchSnapshot();
  });

  it('record view with record arrows (3 of 137)', async () => {
    h.search = `ctx=${LIST_CTX}&i=2`;
    const { container } = await renderRecord();
    await screen.findByText('3 / 137');
    expect(parityHtml(container)).toMatchSnapshot();
  });

  it('record view: Conversation tab', async () => {
    const { container } = await renderRecord();
    const tab = screen.getByRole('tab', { name: 'Conversation' });
    fireEvent.mouseDown(tab);
    fireEvent.click(tab);
    await screen.findByText(
      (_c, el) => el?.getAttribute('data-stub') === 'conversation-pane',
    );
    expect(parityHtml(container)).toMatchSnapshot();
  });

  it('record view: details in edit mode', async () => {
    const { container } = await renderRecord();
    fireEvent.click(screen.getByTestId('contact-details-edit'));
    expect(parityHtml(container)).toMatchSnapshot();
  });

  it('record view: gear menu and the erase confirm', async () => {
    await renderRecord();
    const gear = screen.getByRole('button', { name: 'Actions' });
    fireEvent.pointerDown(gear, { button: 0, pointerType: 'mouse' });
    fireEvent.click(gear);
    const item = await screen.findByRole('menuitem', { name: /Erase contact/ });
    // The menu opens and closes on a motion spring; skipAnimations lands the
    // final keyframe a frame later, not on mount. Snapshot each surface once
    // it has settled (menu fully in, then menu fully gone behind the confirm)
    // so the markup does not depend on how fast the runner is.
    const surface = item.parentElement as HTMLElement;
    await waitFor(() => expect(surface.style.transform).toBe('none'));
    expect(parityHtml(document.body)).toMatchSnapshot('menu');
    fireEvent.click(item);
    await screen.findByRole('alertdialog');
    await waitFor(() => expect(document.querySelector('[role="menu"]')).toBeNull());
    expect(parityHtml(document.body)).toMatchSnapshot('confirm');
  });

  it('record not found', async () => {
    h.get.mockReset().mockRejectedValue(new Error('404'));
    const { container } = render(
      <ContactFormView contactId={RECORD_ID} workspaceId="wsp-1" />,
    );
    await screen.findByText('Contact not found.');
    expect(parityHtml(container)).toMatchSnapshot();
  });

  it('Details tab: loading and not found', () => {
    h.messages = { ...messagesFor(), thread: null, isLoading: true };
    const loading = render(<ContactDetailsTab contactId={RECORD_ID} />);
    expect(parityHtml(loading.container)).toMatchSnapshot('loading');
    loading.unmount();
    h.messages = { ...messagesFor(), thread: null, error: new Error('x') };
    const missing = render(<ContactDetailsTab contactId={RECORD_ID} />);
    expect(parityHtml(missing.container)).toMatchSnapshot('not found');
  });
});

describe('new contact, switch off (parity)', () => {
  beforeEach(() => {
    h.pathname = '/omnichannel/contacts/new';
  });

  it('new-contact form', async () => {
    const { container } = render(<ContactFormView workspaceId="wsp-1" />);
    await screen.findByRole('heading', { name: 'New contact' });
    expect(parityHtml(container)).toMatchSnapshot();
  });

  it('create sends the same request, toast and navigation', async () => {
    render(<ContactFormView workspaceId="wsp-1" />);
    await screen.findByRole('heading', { name: 'New contact' });
    fireEvent.change(screen.getByLabelText('First name'), {
      target: { value: 'Aisyah' },
    });
    fireEvent.change(screen.getByLabelText('Phone *'), {
      target: { value: '+60123456789' },
    });
    fireEvent.change(screen.getByLabelText('Company'), {
      target: { value: 'Kedai' },
    });
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /^Create/ }));
    });
    await waitFor(() => expect(h.create).toHaveBeenCalled());
    await waitFor(() => expect(h.push).toHaveBeenCalled());
    expect({
      create: h.create.mock.calls,
      toasts: h.toastCalls,
      push: h.push.mock.calls,
    }).toMatchSnapshot();
  });

  it('create with a missing phone shows the field error and sends nothing', async () => {
    const { container } = render(<ContactFormView workspaceId="wsp-1" />);
    await screen.findByRole('heading', { name: 'New contact' });
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /^Create/ }));
    });
    await screen.findByText('Phone is required.');
    expect(h.create).not.toHaveBeenCalled();
    expect(parityHtml(container)).toMatchSnapshot();
  });
});
