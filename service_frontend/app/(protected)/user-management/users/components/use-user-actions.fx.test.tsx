/**
 * FX-04: with the Foundryx UIUX switch on, the Impersonate confirm names the
 * user ("Impersonate Jane Doe?"); a row with no name keeps today's words.
 * The switch-off words are pinned by
 * `components/fx/__parity__/followup.parity.test.tsx`.
 */
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { FX_DEFAULT_THEME } from '@/lib/fx/cookies';
import { FxProvider } from '@/providers/fx-provider';
import { ConfirmActionDialog } from '@/components/platform/resource-actions/confirm-action-dialog';
import type { User } from '@/types/user';
import { useUserActions } from './use-user-actions';

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn() }),
}));
vi.mock('next-auth/react', () => ({
  useSession: () => ({ data: { user: { id: 'me', permissions: [] } }, status: 'authenticated' }),
}));
vi.mock('@/hooks/use-impersonation', () => ({
  useImpersonation: () => ({ start: vi.fn() }),
}));
vi.mock('next-themes', () => ({
  useTheme: () => ({ theme: 'light', setTheme: vi.fn() }),
}));

function Harness({ rows }: { rows: User[] }) {
  const impersonate = useUserActions().find((a) => a.id === 'impersonate') ?? null;
  return <ConfirmActionDialog pending={impersonate} rows={rows} onClose={vi.fn()} onConfirm={vi.fn()} />;
}

function renderOn(rows: User[]) {
  render(
    <FxProvider initial initialTheme={FX_DEFAULT_THEME}>
      <Harness rows={rows} />
    </FxProvider>,
  );
}

const user = (name: string | null) =>
  ({ id: 'u-2', name, email: 'jane@example.com', status: 'ACTIVE' }) as unknown as User;

describe('FX-04 Impersonate names the user', () => {
  it('asks "Impersonate Jane Doe?"', async () => {
    renderOn([user('Jane Doe')]);
    expect(await screen.findByRole('heading', { name: 'Impersonate Jane Doe?' })).toBeInTheDocument();
  });

  it('keeps today\'s words when the row has no name', async () => {
    renderOn([user(null)]);
    expect(await screen.findByRole('heading', { name: 'Impersonate this user?' })).toBeInTheDocument();
  });
});
