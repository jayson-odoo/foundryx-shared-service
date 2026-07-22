import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { DateFormatTool, dateFormula } from './date-format-tool';

describe('dateFormula', () => {
  it('composes formatDate(parseDate(value, IN), OUT)', () => {
    expect(dateFormula('yyyy/MM/dd HH:mm:ss', 'yyyy-MM-ddTHH:mm:ssZ')).toBe(
      'formatDate(parseDate(value, "yyyy/MM/dd HH:mm:ss"), "yyyy-MM-ddTHH:mm:ssZ")',
    );
  });
});

describe('DateFormatTool (AC-16-14)', () => {
  it('previews a sample date through the default input→output formats live', () => {
    render(<DateFormatTool onInsert={vi.fn()} />);
    const preview = screen.getByTestId('date-sample-preview');
    // Default input `yyyy/MM/dd HH:mm:ss` sample → ISO output.
    expect(preview).toHaveTextContent('2026/03/18 16:03:21');
    expect(preview).toHaveTextContent('2026-03-18T16:03:21Z');
  });

  it('writes parseDate/formatDate into the formula on insert', () => {
    const onInsert = vi.fn();
    render(<DateFormatTool onInsert={onInsert} />);
    fireEvent.click(screen.getByRole('button', { name: /use this date format/i }));
    expect(onInsert).toHaveBeenCalledWith(
      'formatDate(parseDate(value, "yyyy/MM/dd HH:mm:ss"), "yyyy-MM-ddTHH:mm:ssZ")',
    );
  });
});
