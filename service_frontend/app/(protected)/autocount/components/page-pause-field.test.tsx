import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { pagePauseError, PagePauseField } from './page-pause-field';

describe('pagePauseError (AUTOCOUNT-LOAD-STRATEGY s6)', () => {
  it('accepts blank and 0-90', () => {
    for (const v of [null, undefined, 0, 1.5, 90]) expect(pagePauseError(v)).toBeNull();
  });
  it('refuses the rest with the backend message', () => {
    for (const v of [-1, 91, Number.NaN]) {
      expect(pagePauseError(v)).toBe(
        'Pause between pages must be a number from 0 to 90 seconds (max 90 s: longer pauses make the stock run exceed its 2 h limit).',
      );
    }
  });
});

describe('PagePauseField', () => {
  it('shows the label, the value and the hint', () => {
    render(
      <PagePauseField id="p" value={5} onChange={() => {}} hintText="About 24 pages per run → about 3 min per run" />,
    );
    expect(screen.getByLabelText('Pause between pages (seconds)')).toHaveValue(5);
    expect(screen.getByText('About 24 pages per run → about 3 min per run')).toBeInTheDocument();
  });

  it('clearing it means blank (the connection value)', () => {
    const onChange = vi.fn();
    render(<PagePauseField id="p" value={5} onChange={onChange} />);
    fireEvent.change(screen.getByLabelText('Pause between pages (seconds)'), { target: { value: '' } });
    expect(onChange).toHaveBeenCalledWith(null);
    fireEvent.change(screen.getByLabelText('Pause between pages (seconds)'), { target: { value: '7' } });
    expect(onChange).toHaveBeenCalledWith(7);
  });

  it('shows a server error over the live one', () => {
    render(<PagePauseField id="p" value={95} onChange={() => {}} error="From the server" />);
    expect(screen.getByText('From the server')).toBeInTheDocument();
  });
});
