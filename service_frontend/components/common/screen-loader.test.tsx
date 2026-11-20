/**
 * AC-DLA-49: `ScreenLoader` (the auth-gate loader) keeps a spinner, no
 * loading-word text copy.
 */
import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { ScreenLoader } from './screen-loader';

describe('ScreenLoader', () => {
  it('renders no loading-word text copy', () => {
    const { container } = render(<ScreenLoader />);
    expect(container.textContent).not.toMatch(/Loading/);
  });

  it('renders a spinner', () => {
    const { container } = render(<ScreenLoader />);
    expect(container.querySelector('.animate-spin')).toBeInTheDocument();
  });
});
