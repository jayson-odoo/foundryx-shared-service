/**
 * Quick replies with the Foundryx UIUX switch on (slice W2-WS): creating and
 * saving send exactly what they send with the switch off; the dialog's red
 * action names the shortcut and is greyed until there is a message; the done
 * toasts' Undo reverses through the same API; Delete keeps its deferred
 * window, named for the countdown. Switch off is pinned by
 * `__parity__/quick-replies.parity.test.tsx`. Requests are captured at
 * `apiFetch`, under the real service.
 */
import type { ReactNode } from 'react';
import {
  fireEvent,
  render,
  renderHook,
  screen,
  waitFor,
} from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { QuickReply } from '@/types/omnichannel';
import { FX_DEFAULT_THEME } from '@/lib/fx/cookies';
import { useQuickReplies } from '@/hooks/use-quick-replies';
import { FxProvider } from '@/providers/fx-provider';
import { resetPageActionsForTests } from '@/components/fx/actions/page-actions-context';
import { fxQuickReplyLabel } from './fx-quick-reply-dialog';
import { QuickReplyDialog } from './quick-reply-dialog';
import { fxQuickReplyName } from './quick-reply-fx';
import { useQuickRepliesListConfig } from './use-quick-replies-list-config';

const net = vi.hoisted(() => ({ apiFetch: vi.fn() }));
vi.mock('@/lib/api-client', async (orig) => {
  const real = (await orig()) as Record<string, unknown>;
  return { ...real, apiFetch: net.apiFetch };
});
vi.mock('next-themes', () => ({
  useTheme: () => ({ theme: 'light', setTheme: vi.fn() }),
}));
vi.mock('next/navigation', () => ({
  useRouter: vi.fn(() => ({
    push: vi.fn(),
    prefetch: vi.fn(),
    replace: vi.fn(),
    back: vi.fn(),
  })),
  useSearchParams: vi.fn(() => new URLSearchParams()),
  usePathname: vi.fn(() => '/omnichannel/settings/quick-replies'),
}));

const ITEM: QuickReply = {
  id: 'qr-1',
  workspaceId: 'wsp-1',
  shortcut: '/greeting',
  body: 'Hi there',
};

function look(on: boolean) {
  return function Look({ children }: { children: ReactNode }) {
    return (
      <FxProvider initial={on} initialTheme={FX_DEFAULT_THEME}>
        {children}
      </FxProvider>
    );
  };
}

function writes() {
  return net.apiFetch.mock.calls
    .filter(([, init]) => (init as RequestInit | undefined)?.method)
    .map(([path, init]) => ({
      path,
      method: (init as RequestInit).method,
      body: (init as RequestInit).body ?? null,
    }));
}

beforeEach(() => {
  net.apiFetch.mockReset();
  net.apiFetch.mockImplementation(async (_path: string, init?: RequestInit) => {
    if (
      init?.method === 'POST' ||
      init?.method === 'PATCH' ||
      init?.method === 'PUT'
    ) {
      return { ...ITEM, ...JSON.parse(String(init.body)) };
    }
    if (init?.method === 'DELETE') return undefined;
    return [ITEM];
  });
});
afterEach(() => resetPageActionsForTests());

/** The dialog wired to the real hook, as the page wires it. */
function Harness({ item }: { item: QuickReply | null }) {
  const { create, update } = useQuickReplies('wsp-1');
  return (
    <QuickReplyDialog
      item={item}
      onClose={() => {}}
      onCreate={async (input) => {
        await create(input);
      }}
      onUpdate={async (id, input) => {
        await update(id, input);
      }}
    />
  );
}

async function submitIn(on: boolean, item: QuickReply | null) {
  const view = render(<Harness item={item} />, { wrapper: look(on) });
  await waitFor(() => expect(net.apiFetch).toHaveBeenCalled());
  fireEvent.change(screen.getByLabelText('Shortcut'), {
    target: { value: '  /thanks ' },
  });
  fireEvent.change(screen.getByLabelText(/Message/), {
    target: { value: ' Thank you! ' },
  });
  fireEvent.click(
    screen.getByRole('button', { name: /(Create|Save) .*quick reply/ }),
  );
  await waitFor(() => expect(writes()).toHaveLength(1));
  const sent = writes();
  view.unmount();
  net.apiFetch.mockClear();
  return sent;
}

describe('the same requests in both looks', () => {
  it('create', async () => {
    const off = await submitIn(false, null);
    const on = await submitIn(true, null);
    expect(off[0].body).toBe('{"shortcut":"/thanks","body":"Thank you!"}');
    expect(on).toEqual(off);
  });

  it('save', async () => {
    const off = await submitIn(false, ITEM);
    const on = await submitIn(true, ITEM);
    expect(off).toHaveLength(1);
    expect(on).toEqual(off);
  });

  it('Delete parks the same deferred action, named for the countdown', () => {
    const handlers = { onCreate: vi.fn(), onEdit: vi.fn(), onDelete: vi.fn() };
    const off = renderHook(() => useQuickRepliesListConfig([ITEM], handlers), {
      wrapper: look(false),
    });
    const on = renderHook(() => useQuickRepliesListConfig([ITEM], handlers), {
      wrapper: look(true),
    });
    const del = (c: typeof off.result.current) =>
      c.actions.find((a) => a.id === 'delete')!;
    expect(del(on.result.current).deferred?.actionKey).toBe(
      del(off.result.current).deferred?.actionKey,
    );
    expect(del(on.result.current).deferred?.entityType).toBe('quick_reply');
    expect(del(on.result.current).deferred?.fxName?.([ITEM])).toBe('/greeting');
  });
});

describe('under the new look', () => {
  it('the red action names the shortcut and is greyed until there is a message', async () => {
    render(<Harness item={null} />, { wrapper: look(true) });
    expect(screen.getByText('Enter the message.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Create quick reply/ }));
    expect(writes()).toHaveLength(0);
    expect(fxQuickReplyLabel(false, ' /thanks ')).toBe(
      'Create /thanks quick reply',
    );
    expect(fxQuickReplyLabel(true, '')).toBe('Save quick reply');
  });

  it('a refused save says why under the action', async () => {
    const onCreate = vi
      .fn()
      .mockRejectedValue(new Error('That shortcut is already used.'));
    render(
      <QuickReplyDialog
        item={null}
        onClose={vi.fn()}
        onCreate={onCreate}
        onUpdate={vi.fn()}
      />,
      {
        wrapper: look(true),
      },
    );
    fireEvent.change(screen.getByLabelText(/Message/), {
      target: { value: 'Hello' },
    });
    fireEvent.click(screen.getByRole('button', { name: /Create quick reply/ }));
    expect(
      await screen.findByText('That shortcut is already used.'),
    ).toBeInTheDocument();
  });

  it('names a reply by its shortcut, else the start of its message', () => {
    expect(fxQuickReplyName(ITEM)).toBe('/greeting');
    expect(
      fxQuickReplyName({
        shortcut: null,
        body: 'We will get back to you within one working day.',
      }),
    ).toBe('"We will get back to you within..."');
  });
});
