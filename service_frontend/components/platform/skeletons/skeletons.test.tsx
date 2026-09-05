/**
 * AC-DLA-48: `ListPageSkeleton`/`RecordPageSkeleton` render skeleton blocks
 * (no live data, no network) and hold their generic shape.
 */
import { render } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ListPageSkeleton } from './list-page-skeleton';
import { RecordPageSkeleton } from './record-page-skeleton';

vi.mock('@/providers/settings-provider', () => ({
  useSettings: () => ({ settings: { container: 'fixed' } }),
}));

describe('ListPageSkeleton', () => {
  it('renders skeleton blocks including a pagination strip placeholder', () => {
    const { container } = render(<ListPageSkeleton />);
    expect(container.querySelectorAll('[data-slot="skeleton"]').length).toBeGreaterThan(5);
  });

  it('renders the requested number of row bars at the 60px row height', () => {
    const { container } = render(<ListPageSkeleton rows={3} />);
    expect(container.querySelectorAll('.h-\\[60px\\]').length).toBe(3);
  });
});

describe('RecordPageSkeleton', () => {
  it('renders a toolbar row, identity block, tab strip, and two section cards', () => {
    const { container } = render(<RecordPageSkeleton />);
    expect(container.querySelectorAll('[data-slot="skeleton"]').length).toBeGreaterThan(5);
    expect(container.querySelectorAll('[data-slot="card"]').length).toBe(3); // identity + 2 sections
  });
});
