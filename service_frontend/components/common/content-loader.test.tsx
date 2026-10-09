/**
 * AC-DLA-49: `ContentLoader` renders a `Skeleton` shape (no loading-word
 * text copy) sized by its `variant` prop.
 */
import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { ContentLoader } from './content-loader';

describe('ContentLoader', () => {
  it('renders no loading-word text copy', () => {
    const { container } = render(<ContentLoader />);
    expect(container.textContent).not.toMatch(/Loading/);
  });

  it('defaults to the block variant - one skeleton block', () => {
    const { container } = render(<ContentLoader />);
    expect(container.querySelectorAll('[data-slot="skeleton"]').length).toBe(1);
  });

  it('card variant renders several line bars', () => {
    const { container } = render(<ContentLoader variant="card" />);
    expect(container.querySelectorAll('[data-slot="skeleton"]').length).toBeGreaterThan(1);
  });

  it('inline variant renders one short bar', () => {
    const { container } = render(<ContentLoader variant="inline" />);
    expect(container.querySelectorAll('[data-slot="skeleton"]').length).toBe(1);
  });
});
