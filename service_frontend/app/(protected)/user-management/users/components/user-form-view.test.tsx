/**
 * AC-DLA-50: an unknown user id calls Next's real `notFound()` (caught by
 * `app/(protected)/not-found.tsx`, chrome intact) instead of rendering a
 * hand-rolled inline message.
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
  it('calls notFound() when the hook reports notFound', () => {
    useUserForm.mockReturnValue({ config: null, form: {}, isLoading: false, notFound: true });
    expect(() => render(<UserFormView userId="unknown-id" initialEditing={false} />)).toThrow(
      'NEXT_NOT_FOUND',
    );
    expect(notFound).toHaveBeenCalled();
  });

  it('calls notFound() when config is null even if notFound is false (defensive)', () => {
    useUserForm.mockReturnValue({ config: null, form: {}, isLoading: false, notFound: false });
    expect(() => render(<UserFormView userId="unknown-id" initialEditing={false} />)).toThrow(
      'NEXT_NOT_FOUND',
    );
  });

  it('does not call notFound() while loading', () => {
    notFound.mockClear();
    useUserForm.mockReturnValue({ config: null, form: {}, isLoading: true, notFound: false });
    render(<UserFormView userId="some-id" initialEditing={false} />);
    expect(notFound).not.toHaveBeenCalled();
  });
});
