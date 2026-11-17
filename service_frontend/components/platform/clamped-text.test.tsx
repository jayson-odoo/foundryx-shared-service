import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { TooltipProvider } from '@/components/ui/tooltip';
import { ClampedText } from './clamped-text';

/** Crew pass 70e96f2b: a long name in a one-line table cell was clipped
 * mid-word with no "..." and no full text on hover - the overflow is
 * sideways, and the old measure only checked height. */
const wrap = (ui: React.ReactElement) => render(<TooltipProvider>{ui}</TooltipProvider>);

describe('ClampedText', () => {
  afterEach(() => vi.restoreAllMocks());

  it('one line: ends in an ellipsis (truncate), not a vertical clamp', () => {
    wrap(<ClampedText text="A very long follower name" lines={1} />);
    const p = screen.getByText('A very long follower name');
    expect(p).toHaveClass('truncate');
    expect(p).not.toHaveClass('line-clamp-1');
  });

  it('one line: sideways overflow counts as truncated and offers the full text', async () => {
    vi.spyOn(HTMLElement.prototype, 'scrollWidth', 'get').mockReturnValue(387);
    vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(255);
    wrap(<ClampedText text="A very long follower name" lines={1} />);
    await act(async () => {});
    const p = screen.getByText('A very long follower name');
    // The tooltip trigger wraps it once it is known to be cut.
    expect(p).toHaveAttribute('data-state');
  });

  it('multi-line keeps the line clamp', () => {
    wrap(<ClampedText text="Two lines" lines={2} />);
    expect(screen.getByText('Two lines')).toHaveClass('line-clamp-2');
  });

  it('re-checks on hover: a cut that appears after mount still offers the full text', async () => {
    let width = 100;
    vi.spyOn(HTMLElement.prototype, 'scrollWidth', 'get').mockImplementation(() => width);
    vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(255);
    wrap(<ClampedText text="Name that becomes cut" lines={1} />);
    await act(async () => {});
    const p = screen.getByText('Name that becomes cut');
    expect(p).not.toHaveAttribute('data-state');
    width = 400; // the column narrowed without resizing the text box
    await act(async () => {
      fireEvent.pointerEnter(p);
    });
    expect(screen.getByText('Name that becomes cut')).toHaveAttribute('data-state');
  });
});
