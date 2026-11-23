/**
 * A confirmed action whose `run` rejects (the server refusing an
 * impersonation with a 400 and its reason) must put that reason on screen and
 * never leave an unhandled promise rejection - with the Foundryx UIUX switch
 * on and off, from the row menu and the bulk menu. The menus start actions
 * fire-and-forget after the confirm dialog closes, so before the fix the
 * rejection surfaced nowhere and the browser logged it as uncaught.
 */
import type { ReactNode } from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/lib/api-client';
import { FX_DEFAULT_THEME } from '@/lib/fx/cookies';
import { FxProvider } from '@/providers/fx-provider';
import type { ResourceAction, ResourceActionRuntime } from '@/components/platform/resource-list/types';
import { ActionMenu } from './action-menu';
import { BulkActions } from './bulk-actions';

const toastError = vi.hoisted(() => vi.fn());
vi.mock('@/lib/toast', () => ({
  toast: {
    success: vi.fn(),
    error: toastError,
    info: vi.fn(),
    warning: vi.fn(),
    custom: vi.fn(),
    dismiss: vi.fn(),
    message: vi.fn(),
    fxDone: vi.fn(),
  },
}));
vi.mock('@/hooks/use-can', () => ({ useCan: () => ({ can: () => true }) }));
vi.mock('@/hooks/use-deferred-action', () => ({
  useDeferredAction: () => ({ start: vi.fn(), cancel: vi.fn() }),
}));
vi.mock('next-themes', () => ({
  useTheme: () => ({ theme: 'light', setTheme: vi.fn() }),
}));

const REASON = 'This user can’t be impersonated (inactive, or also an impersonator).';

interface Rec {
  id: string;
}
const rows: Rec[] = [{ id: 'u1' }];
const runtime = { reload: vi.fn() } as unknown as ResourceActionRuntime;

function refusing(message: string, surfaces = { row: true, bulk: true }) {
  return {
    id: 'impersonate',
    label: 'Impersonate',
    surfaces,
    confirm: { title: 'Impersonate this user?', description: 'Acts as them.', confirmLabel: 'Impersonate' },
    run: vi.fn(() => Promise.reject(new ApiError(message, 400))),
  } as unknown as ResourceAction<Rec>;
}

function wrap(fx: boolean) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return fx ? (
      <FxProvider initial initialTheme={FX_DEFAULT_THEME}>
        {children}
      </FxProvider>
    ) : (
      <>{children}</>
    );
  };
}

/** Confirms the open dialog: one click (switch off) or the press and hold
 *  (switch on). */
function confirm(fx: boolean) {
  const button = screen.getByRole('button', { name: /^Impersonate/ });
  if (!fx) {
    fireEvent.click(button);
    return;
  }
  vi.useFakeTimers({
    toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'Date', 'requestAnimationFrame', 'cancelAnimationFrame'],
  });
  fireEvent.pointerDown(button, { button: 0, clientX: 10, clientY: 10 });
  act(() => {
    vi.advanceTimersByTime(3200);
  });
  vi.useRealTimers();
}

const unhandled = vi.fn();
beforeEach(() => {
  toastError.mockClear();
  unhandled.mockClear();
  process.on('unhandledRejection', unhandled);
  window.addEventListener('unhandledrejection', unhandled);
});
afterEach(() => {
  vi.useRealTimers();
  process.off('unhandledRejection', unhandled);
  window.removeEventListener('unhandledrejection', unhandled);
});

/** Lets any rejection left unhandled reach the listeners above. */
async function settle() {
  await new Promise((resolve) => setTimeout(resolve, 20));
}

describe.each([
  ['off', false],
  ['on', true],
])('a refused confirmed action (switch %s)', (_label, fx) => {
  it('row menu: shows the server reason, no unhandled rejection', async () => {
    const action = refusing(REASON);
    render(<ActionMenu actions={[action]} rows={rows} runtime={runtime} surface="row" defaultOpen />, {
      wrapper: wrap(fx),
    });
    fireEvent.click(await screen.findByRole('menuitem', { name: /Impersonate/ }));
    await screen.findByRole('alertdialog');
    confirm(fx);
    await waitFor(() => expect(toastError).toHaveBeenCalledWith(REASON));
    expect(action.run).toHaveBeenCalledTimes(1);
    await settle();
    expect(unhandled).not.toHaveBeenCalled();
  });

  it('bulk menu: shows the server reason, no unhandled rejection', async () => {
    const action = refusing(REASON);
    render(<BulkActions actions={[action]} rows={rows} runtime={runtime} />, {
      wrapper: wrap(fx),
    });
    fireEvent.pointerDown(screen.getByRole('button', { name: 'Bulk actions' }), {
      button: 0,
      ctrlKey: false,
    });
    fireEvent.click(await screen.findByRole('menuitem', { name: /Impersonate/ }));
    await screen.findByRole('alertdialog');
    confirm(fx);
    await waitFor(() => expect(toastError).toHaveBeenCalledWith(REASON));
    await settle();
    expect(unhandled).not.toHaveBeenCalled();
  });

  it('falls back to the generic line when the failure carries no reason', async () => {
    const action = refusing('');
    render(<ActionMenu actions={[action]} rows={rows} runtime={runtime} surface="row" defaultOpen />, {
      wrapper: wrap(fx),
    });
    fireEvent.click(await screen.findByRole('menuitem', { name: /Impersonate/ }));
    await screen.findByRole('alertdialog');
    confirm(fx);
    await waitFor(() => expect(toastError).toHaveBeenCalledWith('The action failed.'));
    await settle();
    expect(unhandled).not.toHaveBeenCalled();
  });
});
