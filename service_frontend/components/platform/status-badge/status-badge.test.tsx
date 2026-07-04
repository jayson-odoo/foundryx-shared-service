import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { StatusBadge, type StatusRegistry } from './status-badge';

type S = 'ACTIVE' | 'BLOCKED';
const registry: StatusRegistry<S> = {
  ACTIVE: { label: 'Active', tone: 'success' },
  BLOCKED: { label: 'Blocked', tone: 'destructive' },
};

describe('StatusBadge', () => {
  it('renders the mapped label for a known status', () => {
    render(<StatusBadge status="ACTIVE" registry={registry} />);
    expect(screen.getByText('Active')).toBeInTheDocument();
  });

  it('falls back to the raw value for an unknown status', () => {
    render(<StatusBadge status={'MYSTERY' as S} registry={registry} />);
    expect(screen.getByText('MYSTERY')).toBeInTheDocument();
  });
});
