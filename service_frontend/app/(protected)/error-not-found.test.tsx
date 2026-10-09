/**
 * AC-DLA-50: `error.tsx` (client, `reset`) and `not-found.tsx` exist and
 * render a friendly message + a recovery action. The "rendered inside the
 * shell" claim (sidebar/header survive) is a Next.js file-convention
 * guarantee (an error/not-found boundary wraps only its OWN segment's
 * children, never the enclosing `layout.tsx`) verified live in the
 * evidence run, not re-asserted here.
 */
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import ProtectedError from './error';
import ProtectedNotFound from './not-found';

vi.mock('@/providers/settings-provider', () => ({
  useSettings: () => ({ settings: { container: 'fixed' } }),
}));

describe('app/(protected)/error.tsx', () => {
  it('renders a message and a Reset button that calls reset()', () => {
    const reset = vi.fn();
    render(<ProtectedError error={new Error('boom')} reset={reset} />);
    expect(screen.getByText('Something went wrong')).toBeInTheDocument();
    screen.getByRole('button', { name: 'Reset' }).click();
    expect(reset).toHaveBeenCalled();
  });
});

describe('app/(protected)/not-found.tsx', () => {
  it('renders a friendly message and a link back to the dashboard', () => {
    render(<ProtectedNotFound />);
    expect(screen.getByText('Not found')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Back to dashboard' })).toHaveAttribute('href', '/');
  });
});
