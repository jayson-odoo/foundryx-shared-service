/**
 * Hold to Copy (slice F3b): the 0.75 s hold, cancelling by moving or letting
 * go, the swallowed click, the clipboard fallback and "Couldn't copy", and
 * nothing at all with the switch off.
 */
import type { ReactNode } from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { FX_DEFAULT_THEME } from '@/lib/fx/cookies';
import { FxProvider } from '@/providers/fx-provider';
import { FormRow } from '@/components/platform/resource-form/form-row';
import { FxHoldToCopy, fxVisibleText } from './hold-to-copy';

vi.mock('next-themes', () => ({
  useTheme: () => ({ theme: 'light', setTheme: vi.fn() }),
}));

// jsdom has no PointerEvent: a MouseEvent carrying the pointer fields.
beforeAll(() => {
  if (typeof window.PointerEvent === 'undefined') {
    class PointerEventStub extends MouseEvent {
      pointerType: string;
      constructor(type: string, init: PointerEventInit = {}) {
        super(type, init);
        this.pointerType = init.pointerType ?? 'mouse';
      }
    }
    window.PointerEvent = PointerEventStub as unknown as typeof PointerEvent;
  }
});

function On({ children }: { children: ReactNode }) {
  return (
    <FxProvider initial initialTheme={FX_DEFAULT_THEME}>
      {children}
    </FxProvider>
  );
}

const writeText = vi.fn<(text: string) => Promise<void>>();

beforeEach(() => {
  vi.useFakeTimers();
  writeText.mockReset();
  writeText.mockResolvedValue(undefined);
  Object.defineProperty(navigator, 'clipboard', {
    configurable: true,
    value: { writeText },
  });
});

afterEach(() => {
  vi.useRealTimers();
});

const down = (el: Element, x = 20, y = 20) =>
  fireEvent.pointerDown(el, { button: 0, clientX: x, clientY: y, pointerType: 'mouse' });

async function flush() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

function value() {
  return document.querySelector('[data-fx-h2c]') as HTMLElement;
}

describe('FxHoldToCopy', () => {
  it('copies the visible text after a 0.75 s hold and says "Copied" for 1.4 s', async () => {
    render(
      <On>
        <FxHoldToCopy>
          INV-2026-014<span className="sr-only"> invoice number</span>
        </FxHoldToCopy>
      </On>,
    );
    const el = value();
    fireEvent.pointerEnter(el, { clientX: 20, clientY: 20, pointerType: 'mouse' });
    expect(document.querySelector('[data-fx-copy-tip="hover"]')).not.toBeNull();

    down(el);
    expect(document.querySelector('[data-fx-h2c-ring]')).not.toBeNull();
    act(() => {
      vi.advanceTimersByTime(740);
    });
    expect(writeText).not.toHaveBeenCalled();
    act(() => {
      vi.advanceTimersByTime(10);
    });
    expect(writeText).toHaveBeenCalledWith('INV-2026-014');
    await flush();
    expect(screen.getByText('Copied')).toBeInTheDocument();

    fireEvent.pointerUp(el, { pointerType: 'mouse' });
    fireEvent.pointerLeave(el, { pointerType: 'mouse' });
    act(() => {
      vi.advanceTimersByTime(1399);
    });
    expect(screen.getByText('Copied')).toBeInTheDocument();
    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(screen.queryByText('Copied')).toBeNull();
    expect(document.querySelector('[data-fx-copy-tip]')).toBeNull();
  });

  it('letting go early cancels', () => {
    render(
      <On>
        <FxHoldToCopy>RM 189.00</FxHoldToCopy>
      </On>,
    );
    const el = value();
    down(el);
    act(() => {
      vi.advanceTimersByTime(500);
    });
    fireEvent.pointerUp(el, { pointerType: 'mouse' });
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(writeText).not.toHaveBeenCalled();
  });

  it('moving more than 6px cancels; 6px or less does not', () => {
    render(
      <On>
        <FxHoldToCopy>Alpha Tan</FxHoldToCopy>
      </On>,
    );
    const el = value();
    down(el, 20, 20);
    fireEvent.pointerMove(el, { clientX: 26, clientY: 20, pointerType: 'mouse' });
    act(() => {
      vi.advanceTimersByTime(750);
    });
    expect(writeText).toHaveBeenCalledTimes(1);

    writeText.mockClear();
    down(el, 20, 20);
    fireEvent.pointerMove(el, { clientX: 27, clientY: 20, pointerType: 'mouse' });
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(writeText).not.toHaveBeenCalled();
  });

  it('the click that ends a hold never reaches the row or link under it', async () => {
    const onRow = vi.fn();
    render(
      <On>
        <div role="presentation" onClick={onRow} onKeyDown={onRow}>
          <FxHoldToCopy>QT-2026-014</FxHoldToCopy>
        </div>
      </On>,
    );
    const el = value();
    down(el);
    act(() => {
      vi.advanceTimersByTime(750);
    });
    await flush();
    fireEvent.pointerUp(el, { pointerType: 'mouse' });
    fireEvent.click(el);
    expect(onRow).not.toHaveBeenCalled();
    // A plain click still opens the row.
    fireEvent.click(el);
    expect(onRow).toHaveBeenCalledTimes(1);
  });

  it('falls back to the copy command, then says "Couldn\'t copy"', async () => {
    writeText.mockRejectedValue(new Error('denied'));
    const exec = vi.fn(() => false);
    Object.defineProperty(document, 'execCommand', { configurable: true, value: exec });
    render(
      <On>
        <FxHoldToCopy>22</FxHoldToCopy>
      </On>,
    );
    down(value());
    act(() => {
      vi.advanceTimersByTime(750);
    });
    await flush();
    expect(exec).toHaveBeenCalledWith('copy');
    expect(screen.getByText("Couldn't copy")).toBeInTheDocument();
  });

  it('copies with the copy command when the clipboard is refused but the command works', async () => {
    writeText.mockRejectedValue(new Error('denied'));
    Object.defineProperty(document, 'execCommand', { configurable: true, value: vi.fn(() => true) });
    render(
      <On>
        <FxHoldToCopy>22</FxHoldToCopy>
      </On>,
    );
    down(value());
    act(() => {
      vi.advanceTimersByTime(750);
    });
    await flush();
    expect(screen.getByText('Copied')).toBeInTheDocument();
  });

  it('renders the value untouched with the switch off', () => {
    const { container } = render(<FxHoldToCopy>INV-1</FxHoldToCopy>);
    expect(container.innerHTML).toBe('INV-1');
  });

  it('leaves screen-reader-only words and no-copy parts out', () => {
    const el = document.createElement('span');
    el.innerHTML = 'Lim <span class="sr-only">phone</span>012 <b data-fx-no-copy="">Mobile:</b>345';
    expect(fxVisibleText(el)).toBe('Lim 012 345');
  });

  it('makes a record page plain value copyable, never its fields', () => {
    render(
      <On>
        <FormRow label="Email">alpha@example.com</FormRow>
        <FormRow label="Name">
          <input aria-label="Name" defaultValue="Alpha Tan" />
        </FormRow>
      </On>,
    );
    expect(screen.getByText('alpha@example.com').closest('[data-fx-h2c]')).not.toBeNull();
    expect(screen.getByLabelText('Name').closest('[data-fx-h2c]')).toBeNull();
  });
});
