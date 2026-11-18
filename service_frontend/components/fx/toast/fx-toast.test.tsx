/**
 * The fx done toast and the fx deferred countdown (Foundryx UIUX switch on).
 */
import type { ReactNode } from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { FX_DEFAULT_THEME } from '@/lib/fx/cookies';
import { FxProvider } from '@/providers/fx-provider';
import { toast } from '@/lib/toast';
import { Toaster } from '@/components/ui/sonner';
import { DeferredCountdown } from '@/components/platform/resource-actions/deferred-action-button';
import { FxToast, fxDoneDetail } from './fx-toast';
import { fxCountdownLabel } from './fx-deferred-countdown';

vi.mock('next-themes', () => ({
  useTheme: () => ({ theme: 'light', setTheme: vi.fn() }),
}));

function On({ children }: { children: ReactNode }) {
  return (
    <FxProvider initial initialTheme={FX_DEFAULT_THEME}>
      {children}
    </FxProvider>
  );
}

beforeEach(() => {
  vi.useFakeTimers({
    toFake: [
      'setTimeout',
      'clearTimeout',
      'setInterval',
      'clearInterval',
      'Date',
      'requestAnimationFrame',
      'cancelAnimationFrame',
    ],
  });
  vi.setSystemTime(new Date('2026-11-18T08:00:00.000Z'));
});
afterEach(() => vi.useRealTimers());

describe('FxToast', () => {
  it('says what, for whom, how many and by whom', () => {
    expect(
      fxDoneDetail({
        what: 'Conversation assigned to Kay',
        forWhom: 'Lim Wei Jie',
        byWhom: 'Jayden',
      }),
    ).toBe('Lim Wei Jie, by Jayden');
    render(
      <On>
        <FxToast what="12 products moved to Archived" byWhom="Kay" onClose={vi.fn()} />
      </On>,
    );
    expect(screen.getByRole('status')).toHaveTextContent(
      '12 products moved to Archived',
    );
    expect(screen.getByText('by Kay')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Undo' })).toBeNull();
  });

  it('closes after 6 s, and pauses while the pointer is on it', () => {
    const onClose = vi.fn();
    render(
      <On>
        <FxToast what="User saved" onClose={onClose} />
      </On>,
    );
    act(() => {
      vi.advanceTimersByTime(4000);
    });
    fireEvent.pointerEnter(screen.getByRole('status'));
    act(() => {
      vi.advanceTimersByTime(10_000);
    });
    expect(onClose).not.toHaveBeenCalled();
    fireEvent.pointerLeave(screen.getByRole('status'));
    act(() => {
      vi.advanceTimersByTime(1900);
    });
    expect(onClose).not.toHaveBeenCalled();
    act(() => {
      vi.advanceTimersByTime(200);
    });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('Undo reverses and closes', () => {
    const undo = vi.fn();
    const onClose = vi.fn();
    render(
      <On>
        <FxToast what="Contact tagged VIP" undo={undo} onClose={onClose} />
      </On>,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Undo' }));
    expect(undo).toHaveBeenCalledTimes(1);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('toast.fxDone renders it through the one toast door', () => {
    render(
      <On>
        <Toaster />
      </On>,
    );
    act(() => {
      toast.fxDone({ what: 'Lim Wei Jie assigned to Kay', undo: vi.fn() });
    });
    act(() => {
      vi.advanceTimersByTime(50);
    });
    expect(screen.getByText('Lim Wei Jie assigned to Kay')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Undo' })).toBeInTheDocument();
  });
});

describe('fx deferred countdown', () => {
  it('words the wait the playbook way', () => {
    expect(fxCountdownLabel('Deleting', 7400, 12, 'contacts')).toBe(
      'Deleting 12 contacts in 8 s',
    );
    expect(fxCountdownLabel('Deleting', 4100)).toBe('Deleting in 5 s');
    expect(fxCountdownLabel('Deleting', 0)).toBe('Deleting…');
  });

  it('offers Undo, keeps the tenant window and never pauses under the pointer', () => {
    const onCancel = vi.fn();
    render(
      <On>
        <DeferredCountdown
          verb="Deleting"
          commitAt="2026-11-18T08:00:10.000Z"
          windowSeconds={10}
          count={12}
          noun="contacts"
          onCancel={onCancel}
          fxSurface="toast"
        />
      </On>,
    );
    expect(screen.getByRole('timer')).toHaveTextContent(
      'Deleting 12 contacts in 10 s',
    );
    fireEvent.pointerEnter(screen.getByTestId('deferred-countdown'));
    act(() => {
      vi.advanceTimersByTime(2000);
    });
    expect(screen.getByRole('timer')).toHaveTextContent(
      'Deleting 12 contacts in 8 s',
    );
    fireEvent.click(screen.getByRole('button', { name: 'Undo' }));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });
});
