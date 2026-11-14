/**
 * AC-DLA-50: an unknown user id calls Next's real `notFound()` (caught by
 * `app/(protected)/not-found.tsx`, chrome intact) instead of rendering a
 * hand-rolled inline message.
 *
 * Fix round 1 item 2: a REAL 404 is the ONLY thing that reaches `notFound()`
 * - a 500/network/403 load failure sets `loadError` instead, which the view
 * throws DURING RENDER so `app/(protected)/error.tsx` (Reset, chrome intact)
 * catches it. The pre-fix `.catch(() => setNotFound(true))` turned every
 * failure into notFound(); that's the exact regression these tests guard.
 */
import { render } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { UserFormView } from './user-form-view';

const notFound = vi.fn(() => {
  throw new Error('NEXT_NOT_FOUND');
});

vi.mock('next/navigation', () => ({
  notFound: () => notFound(),
}));

const useUserForm = vi.fn();
vi.mock('./use-user-form', () => ({
  useUserForm: (...args: unknown[]) => useUserForm(...args),
}));

vi.mock('@/providers/settings-provider', () => ({
  useSettings: () => ({ settings: { container: 'fixed' } }),
}));

describe('UserFormView', () => {
  it('calls notFound() when the hook reports a real 404', () => {
    useUserForm.mockReturnValue({
      config: null,
      form: {},
      isLoading: false,
      notFound: true,
      loadError: null,
    });
    expect(() => render(<UserFormView userId="unknown-id" initialEditing={false} />)).toThrow(
      'NEXT_NOT_FOUND',
    );
    expect(notFound).toHaveBeenCalled();
  });

  it('calls notFound() when config is null even if notFound is false (defensive, no load error)', () => {
    useUserForm.mockReturnValue({
      config: null,
      form: {},
      isLoading: false,
      notFound: false,
      loadError: null,
    });
    expect(() => render(<UserFormView userId="unknown-id" initialEditing={false} />)).toThrow(
      'NEXT_NOT_FOUND',
    );
  });

  it('does not call notFound() while loading', () => {
    notFound.mockClear();
    useUserForm.mockReturnValue({
      config: null,
      form: {},
      isLoading: true,
      notFound: false,
      loadError: null,
    });
    render(<UserFormView userId="some-id" initialEditing={false} />);
    expect(notFound).not.toHaveBeenCalled();
  });

  it('a load error (500/network/403) does NOT call notFound() - it throws for the error boundary', () => {
    notFound.mockClear();
    useUserForm.mockReturnValue({
      config: null,
      form: {},
      isLoading: false,
      notFound: false,
      loadError: new Error('Internal Server Error'),
    });
    expect(() => render(<UserFormView userId="some-id" initialEditing={false} />)).toThrow(
      'Internal Server Error',
    );
    expect(notFound).not.toHaveBeenCalled();
  });
});
