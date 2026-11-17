import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ClampedText } from './clamped-text';

describe('ClampedText', () => {
  it('one line cuts a long unbreakable string with an ellipsis', () => {
    render(<ClampedText text="https://consumer.example.com/a-very-long-receiver-path" lines={1} />);
    const el = screen.getByText(/consumer\.example\.com/);
    expect(el.className).toContain('text-ellipsis');
    expect(el.className).toContain('whitespace-nowrap');
    expect(el.className).not.toContain('line-clamp-1');
  });

  it('several lines still clamp and wrap long words', () => {
    render(<ClampedText text="Long title" lines={2} />);
    expect(screen.getByText('Long title').className).toContain('line-clamp-2');
    expect(screen.getByText('Long title').className).toContain('break-words');
  });
});
