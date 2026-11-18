/**
 * F2 primitives under the Foundryx UIUX switch: the red action, the page
 * actions registry, Other Actions, the confirm dialog with its press and hold
 * and typed variant, and the pulse.
 */
import type { ReactNode } from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { FX_DEFAULT_THEME } from '@/lib/fx/cookies';
import { FxProvider } from '@/providers/fx-provider';
import { FxMainAction } from './main-action';
import {
  resetPageActionsForTests,
  useHideMainAction,
  usePageActions,
  useRegisterMainAction,
  type FxMainActionSpec,
} from './page-actions-context';
import { FxOtherActions, splitOtherActions } from './other-actions';
import { FxConfirmDialog, fxTypedMatches } from './confirm-dialog';
import { pulseFxTarget } from './pulse';

function On({ children }: { children: ReactNode }) {
  return (
    <FxProvider initial initialTheme={FX_DEFAULT_THEME}>
      {children}
    </FxProvider>
  );
}

afterEach(() => {
  resetPageActionsForTests();
});

describe('FxMainAction', () => {
  it('gives screen readers the full label and keeps the short one on screen', () => {
    render(
      <On>
        <FxMainAction
          label="Record payment"
          fullLabel="Record RM 2,500.00 from Client E"
        />
      </On>,
    );
    const button = screen.getByRole('button', {
      name: 'Record RM 2,500.00 from Client E',
    });
    expect(button).toHaveTextContent('Record payment');
  });

  it('runs its action on click', () => {
    const onClick = vi.fn();
    render(
      <On>
        <FxMainAction label="Add contact" onClick={onClick} />
      </On>,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Add contact' }));
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it('when blocked, shows the reason, does not run, and pulses its target', () => {
    const onClick = vi.fn();
    render(
      <On>
        <div data-fx-pulse-target="clients">Clients</div>
        <FxMainAction
          label="Send reminders"
          onClick={onClick}
          blocked={{ reason: 'Tick at least one client.', pulseTarget: 'clients' }}
        />
      </On>,
    );
    const button = screen.getByRole('button', { name: 'Send reminders' });
    expect(button).toHaveAttribute('aria-disabled', 'true');
    expect(button).toHaveAccessibleDescription('Tick at least one client.');
    fireEvent.click(button);
    expect(onClick).not.toHaveBeenCalled();
    expect(screen.getByText('Clients')).toHaveAttribute('data-fx-pulsing');
  });

  it('while working, a second press does nothing', () => {
    const onClick = vi.fn();
    render(
      <On>
        <FxMainAction label="Save user" onClick={onClick} working />
      </On>,
    );
    const button = screen.getByRole('button', { name: 'Save user' });
    expect(button).toHaveAttribute('aria-busy', 'true');
    fireEvent.click(button);
    expect(onClick).not.toHaveBeenCalled();
  });
});

describe('pulseFxTarget', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it('marks every named target for 1.8 s', () => {
    render(
      <div>
        <span data-fx-pulse-target="qty">a</span>
        <span data-fx-pulse-target="qty">b</span>
      </div>,
    );
    expect(pulseFxTarget('qty')).toBe(2);
    expect(screen.getByText('a')).toHaveAttribute('data-fx-pulsing');
    act(() => {
      vi.advanceTimersByTime(1800);
    });
    expect(screen.getByText('a')).not.toHaveAttribute('data-fx-pulsing');
  });
});

function Shows() {
  const page = usePageActions();
  return (
    <output data-testid="shown">
      {page.hidden ? 'hidden' : (page.main?.label ?? 'none')}
    </output>
  );
}

function Registers({ spec }: { spec: FxMainActionSpec | null }) {
  useRegisterMainAction(spec);
  return null;
}

function Hides({ active }: { active: boolean }) {
  useHideMainAction(active);
  return null;
}

const SAVE: FxMainActionSpec = { id: 'save', label: 'Save user' };
const CLOSE: FxMainActionSpec = { id: 'close', label: 'Close conversation' };

describe('page actions registry', () => {
  it('keeps one main action: the latest wins and the earlier one returns', () => {
    const { rerender } = render(
      <>
        <Shows />
        <Registers spec={SAVE} />
      </>,
    );
    expect(screen.getByTestId('shown')).toHaveTextContent('Save user');
    rerender(
      <>
        <Shows />
        <Registers spec={SAVE} />
        <Registers spec={CLOSE} />
      </>,
    );
    expect(screen.getByTestId('shown')).toHaveTextContent('Close conversation');
    rerender(
      <>
        <Shows />
        <Registers spec={SAVE} />
      </>,
    );
    expect(screen.getByTestId('shown')).toHaveTextContent('Save user');
  });

  it('hides the main action while a dialog is open', () => {
    const { rerender } = render(
      <>
        <Shows />
        <Registers spec={SAVE} />
        <Hides active />
      </>,
    );
    expect(screen.getByTestId('shown')).toHaveTextContent('hidden');
    rerender(
      <>
        <Shows />
        <Registers spec={SAVE} />
        <Hides active={false} />
      </>,
    );
    expect(screen.getByTestId('shown')).toHaveTextContent('Save user');
  });

  it('an fx confirm dialog hides it while open', () => {
    const { rerender } = render(
      <On>
        <Shows />
        <Registers spec={SAVE} />
        <FxConfirmDialog
          open
          title="Purge acme?"
          keepLabel="Keep tenant"
          actionLabel="Purge tenant"
          onKeep={vi.fn()}
          onConfirm={vi.fn()}
        />
      </On>,
    );
    expect(screen.getByTestId('shown')).toHaveTextContent('hidden');
    rerender(
      <On>
        <Shows />
        <Registers spec={SAVE} />
        <FxConfirmDialog
          open={false}
          title="Purge acme?"
          keepLabel="Keep tenant"
          actionLabel="Purge tenant"
          onKeep={vi.fn()}
          onConfirm={vi.fn()}
        />
      </On>,
    );
    expect(screen.getByTestId('shown')).toHaveTextContent('Save user');
  });
});

describe('Other Actions', () => {
  const make = (n: number) =>
    Array.from({ length: n }, (_, i) => ({
      id: `a${i}`,
      label: `Action ${i}`,
      icon: 'refresh' as const,
      onClick: vi.fn(),
    }));

  it('splits past four into a More menu', () => {
    expect(splitOtherActions(make(4)).more).toHaveLength(0);
    const split = splitOtherActions(make(6));
    expect(split.shown).toHaveLength(4);
    expect(split.more).toHaveLength(2);
  });

  it('shows no More button up to four, and one past four', () => {
    const { rerender } = render(
      <On>
        <FxOtherActions actions={make(4)} />
      </On>,
    );
    expect(screen.queryByRole('button', { name: 'More' })).toBeNull();
    expect(screen.getAllByRole('button')).toHaveLength(4);
    rerender(
      <On>
        <FxOtherActions actions={make(5)} />
      </On>,
    );
    expect(screen.getByRole('button', { name: 'More' })).toBeInTheDocument();
    expect(screen.getAllByRole('button')).toHaveLength(5);
  });

  it('labels each icon button and greys one that cannot apply', () => {
    const onClick = vi.fn();
    render(
      <On>
        <FxOtherActions
          actions={[
            {
              id: 'send',
              label: 'Send reminder',
              icon: 'reminder',
              onClick,
              disabledReason: '2 are already sent',
            },
          ]}
        />
      </On>,
    );
    const button = screen.getByRole('button', { name: 'Send reminder' });
    expect(button).toHaveAttribute('aria-disabled', 'true');
    fireEvent.click(button);
    expect(onClick).not.toHaveBeenCalled();
  });
});

describe('FxConfirmDialog press and hold', () => {
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
  });
  afterEach(() => vi.useRealTimers());

  function renderHold(onConfirm = vi.fn()) {
    render(
      <On>
        <FxConfirmDialog
          open
          title="Impersonate Kay?"
          line="You act as Kay until you stop."
          keepLabel="Go back"
          actionLabel="Impersonate user"
          onKeep={vi.fn()}
          onConfirm={onConfirm}
        />
      </On>,
    );
    return {
      onConfirm,
      button: screen.getByRole('button', { name: /Impersonate user/ }),
    };
  }

  it('starts on the safe button, and a click alone does nothing', () => {
    const { button, onConfirm } = renderHold();
    expect(screen.getByRole('button', { name: 'Go back' })).toHaveFocus();
    expect(button).toHaveAttribute('title', 'Press and hold for 3 seconds');
    fireEvent.click(button);
    act(() => {
      vi.advanceTimersByTime(4000);
    });
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it('counts 3.0 down to 0.0 and runs once the hold completes', () => {
    const { button, onConfirm } = renderHold();
    fireEvent.pointerDown(button, { button: 0, clientX: 10, clientY: 10 });
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(button.querySelector('[data-fx-countdown]')).toHaveTextContent('2.0');
    expect(screen.getByRole('status')).toHaveTextContent('Hold to confirm');
    act(() => {
      vi.advanceTimersByTime(2100);
    });
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it('letting go early cancels', () => {
    const { button, onConfirm } = renderHold();
    fireEvent.pointerDown(button, { button: 0, clientX: 10, clientY: 10 });
    act(() => {
      vi.advanceTimersByTime(2000);
    });
    fireEvent.pointerUp(button);
    act(() => {
      vi.advanceTimersByTime(3000);
    });
    expect(onConfirm).not.toHaveBeenCalled();
    expect(button.querySelector('[data-fx-countdown]')).toHaveTextContent('');
  });

  it('moving more than 10px cancels; a small wobble does not', () => {
    const { button, onConfirm } = renderHold();
    fireEvent.pointerDown(button, { button: 0, clientX: 10, clientY: 10 });
    fireEvent.pointerMove(button, { clientX: 16, clientY: 14 });
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(button.querySelector('[data-fx-countdown]')).toHaveTextContent('2.0');
    fireEvent.pointerMove(button, { clientX: 25, clientY: 10 });
    act(() => {
      vi.advanceTimersByTime(3000);
    });
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it('holds with the keyboard too (Space)', () => {
    const { button, onConfirm } = renderHold();
    fireEvent.keyDown(button, { key: ' ' });
    act(() => {
      vi.advanceTimersByTime(3100);
    });
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });
});

describe('FxConfirmDialog typed', () => {
  it('matches ignoring case and spaces', () => {
    expect(fxTypedMatches('lim wei jie', 'Lim Wei Jie')).toBe(true);
    expect(fxTypedMatches('LimWeiJie', 'Lim Wei Jie')).toBe(true);
    expect(fxTypedMatches(' QT-2026-014 ', 'qt-2026-014')).toBe(true);
    expect(fxTypedMatches('Lim', 'Lim Wei Jie')).toBe(false);
    expect(fxTypedMatches('', '')).toBe(false);
  });

  it('replaces the hold: greyed with its reason until the name matches, then one click', () => {
    const onConfirm = vi.fn();
    render(
      <On>
        <FxConfirmDialog
          open
          title="Erase Lim Wei Jie?"
          line="Their messages and files are erased too, and none of it comes back."
          keepLabel="Keep contact"
          actionLabel="Erase contact"
          destructive
          typed={{ expected: 'Lim Wei Jie' }}
          onKeep={vi.fn()}
          onConfirm={onConfirm}
        />
      </On>,
    );
    const action = screen.getByRole('button', { name: 'Erase contact' });
    expect(action).not.toHaveAttribute('title');
    expect(action).toHaveAttribute('aria-disabled', 'true');
    expect(screen.getByText('Type the name to confirm.')).toBeInTheDocument();
    fireEvent.click(action);
    expect(onConfirm).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText('Type "Lim Wei Jie"'), {
      target: { value: 'lim wei JIE' },
    });
    expect(action).not.toHaveAttribute('aria-disabled');
    expect(screen.queryByText('Type the name to confirm.')).toBeNull();
    fireEvent.click(action);
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it('Esc chooses the safe button', () => {
    const onKeep = vi.fn();
    render(
      <On>
        <FxConfirmDialog
          open
          title="Purge acme?"
          keepLabel="Keep tenant"
          actionLabel="Purge tenant"
          destructive
          typed={{ expected: 'acme' }}
          onKeep={onKeep}
          onConfirm={vi.fn()}
        />
      </On>,
    );
    fireEvent.keyDown(screen.getByRole('alertdialog'), { key: 'Escape' });
    expect(onKeep).toHaveBeenCalled();
  });
});
