/** RichTextField - WYSIWYG toolbar emits real tags (no typed-tag escaping). */
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { RichTextField } from './rich-text-field';

describe('RichTextField', () => {
  it('seeds the editor with the value as real HTML, not escaped text', () => {
    render(
      <RichTextField value="<b>Hello</b> world" onChange={vi.fn()} fields={[]} aria-label="Body" />,
    );
    const box = screen.getByTestId('rich-text-editable');
    // The <b> is a real element, not literal '&lt;b&gt;'.
    expect(box.querySelector('b')?.textContent).toBe('Hello');
    expect(box.textContent).toBe('Hello world');
  });

  it('commits innerHTML on input', () => {
    const onChange = vi.fn();
    render(<RichTextField value="" onChange={onChange} fields={[]} aria-label="Body" />);
    const box = screen.getByTestId('rich-text-editable');
    box.innerHTML = '<i>typed via toolbar</i>';
    fireEvent.input(box);
    expect(onChange).toHaveBeenCalledWith('<i>typed via toolbar</i>');
  });

  it('renders the formatting toolbar', () => {
    render(<RichTextField value="" onChange={vi.fn()} fields={[]} aria-label="Body" />);
    for (const label of ['Bold', 'Italic', 'Underline', 'Bulleted list', 'Numbered list', 'Insert link']) {
      expect(screen.getByLabelText(label)).toBeInTheDocument();
    }
  });

  it('shows merge-field chips', () => {
    render(
      <RichTextField
        value=""
        onChange={vi.fn()}
        fields={[{ key: 'recipient.firstName', label: 'First name', sample: 'Alex' }]}
        aria-label="Body"
      />,
    );
    expect(screen.getByTestId('merge-chip-recipient.firstName')).toBeInTheDocument();
  });
});
