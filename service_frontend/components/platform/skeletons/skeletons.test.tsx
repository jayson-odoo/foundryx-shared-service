/**
 * AC-DLA-48: `ListPageSkeleton`/`RecordPageSkeleton`/`PageSkeleton` render
 * skeleton blocks (no live data, no network) and hold their generic shape.
 * Each carries a `data-skeleton` discriminator so `loading-inventory.test.tsx`
 * can assert a qualifying segment's `loading.tsx` renders the RIGHT one, not
 * merely "some skeleton block" (fix round 1 item 1).
 */
import { render } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ListPageSkeleton } from './list-page-skeleton';
import { RecordPageSkeleton } from './record-page-skeleton';
import { PageSkeleton } from './page-skeleton';

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

  it('carries the "list" discriminator', () => {
    const { container } = render(<ListPageSkeleton />);
    expect(container.querySelector('[data-skeleton="list"]')).not.toBeNull();
  });
});

describe('RecordPageSkeleton', () => {
  it('renders a toolbar row, identity block, tab strip, and two section cards', () => {
    const { container } = render(<RecordPageSkeleton />);
    expect(container.querySelectorAll('[data-slot="skeleton"]').length).toBeGreaterThan(5);
    expect(container.querySelectorAll('[data-slot="card"]').length).toBe(3); // identity + 2 sections
  });

  it('carries the "record" discriminator', () => {
    const { container } = render(<RecordPageSkeleton />);
    expect(container.querySelector('[data-skeleton="record"]')).not.toBeNull();
  });
});

describe('PageSkeleton', () => {
  it('renders a title block and exactly one section card - no rows, no pagination', () => {
    const { container } = render(<PageSkeleton />);
    expect(container.querySelectorAll('[data-slot="skeleton"]').length).toBeGreaterThan(3);
    expect(container.querySelectorAll('[data-slot="card"]').length).toBe(1);
    expect(container.querySelectorAll('.h-\\[60px\\]').length).toBe(0);
  });

  it('carries the "page" discriminator', () => {
    const { container } = render(<PageSkeleton />);
    expect(container.querySelector('[data-skeleton="page"]')).not.toBeNull();
  });
});
