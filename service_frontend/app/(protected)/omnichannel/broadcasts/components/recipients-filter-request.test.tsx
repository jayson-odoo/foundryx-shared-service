/**
 * The Recipients tab's state filter with two states ticked, in both looks:
 * the exact request that leaves the browser. The real list, list config and
 * broadcast service run here; only `apiFetch` is mocked. The API takes one
 * state or a comma-separated list (`state=sent,read`), covered on the server
 * by `test_recipients_state_filter_one_or_several`.
 */
import type { ReactNode } from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { FX_DEFAULT_THEME } from '@/lib/fx/cookies';
import { FxProvider } from '@/providers/fx-provider';
import { ResourceList } from '@/components/platform/resource-list/resource-list';
import { resetPageActionsForTests } from '@/components/fx/actions/page-actions-context';
import { useRecipientsListConfig } from './use-recipients-list-config';

const h = vi.hoisted(() => ({ paths: [] as string[] }));

vi.mock('@/lib/api-client', () => ({
  ApiError: class ApiError extends Error {},
  apiFetch: (path: string) => {
    h.paths.push(path);
    return Promise.resolve({
      data: [
        {
          id: 'rec-1',
          contactId: 'c-1',
          contactName: 'Alex Tan',
          phone: '+60120001111',
          state: 'sent',
          skipReason: null,
          errorCode: null,
          errorText: null,
          attemptedAt: null,
        },
      ],
      total: 1,
      page: 0,
    });
  },
}));
vi.mock('next-themes', () => ({
  useTheme: () => ({ theme: 'light', setTheme: vi.fn() }),
}));
vi.mock('next/navigation', () => ({
  useRouter: vi.fn(() => ({ push: vi.fn(), prefetch: vi.fn(), replace: vi.fn() })),
  useSearchParams: vi.fn(() => new URLSearchParams()),
  usePathname: vi.fn(() => '/omnichannel/broadcasts/bc-1'),
}));
vi.mock('next-auth/react', () => ({
  useSession: () => ({
    data: { user: { permissions: [], timezone: 'Asia/Kuala_Lumpur' } },
    status: 'authenticated',
  }),
}));
vi.mock('@/lib/impersonation-store', () => ({ useImpersonationSession: () => null }));
vi.mock('@/services/terminology-service', () => ({
  terminologyService: { getTerminology: vi.fn().mockResolvedValue({}) },
}));
vi.mock('@/providers/import-activity-provider', () => ({
  useImportActivity: () => ({ openImport: vi.fn() }),
}));
vi.mock('@/services/preferences-service', () => ({
  preferencesService: { get: vi.fn(async () => null), save: vi.fn(async () => undefined) },
}));

const BASE = '/omnichannel/workspaces/wsp-1/broadcasts/bc-1/recipients';

function Recipients() {
  const { config } = useRecipientsListConfig('wsp-1', 'bc-1');
  return <ResourceList config={config} />;
}

function On({ children }: { children: ReactNode }) {
  return (
    <FxProvider initial initialTheme={FX_DEFAULT_THEME}>
      {children}
    </FxProvider>
  );
}

beforeEach(() => {
  h.paths.length = 0;
});
afterEach(() => resetPageActionsForTests());

describe('Recipients state filter with two states: the request sent', () => {
  it('switch off: "is any of" Sent and Read asks for state=sent,read', async () => {
    render(<Recipients />);
    await waitFor(() => expect(h.paths).toEqual([`${BASE}?page=0&pageSize=25`]));

    await userEvent.click(screen.getByRole('button', { name: /Filters/ }));
    expect(await screen.findByLabelText('Filter operator')).toHaveTextContent('is any of');
    const comboboxes = screen.getAllByRole('combobox');
    await userEvent.click(comboboxes[comboboxes.length - 1]);
    await userEvent.click(await screen.findByRole('option', { name: 'Sent' }));
    await userEvent.click(screen.getByRole('option', { name: 'Read' }));
    // The state picker is still open over the builder, so Apply is behind it.
    fireEvent.click(screen.getByRole('button', { name: 'Apply', hidden: true }));

    await waitFor(() => expect(h.paths.at(-1)).toBe(`${BASE}?page=0&pageSize=25&state=sent%2Cread`));
    expect(new URLSearchParams(h.paths.at(-1)!.split('?')[1]).get('state')).toBe('sent,read');
  });

  it('switch on: ticking Sent and Read in the State header asks for state=sent,read', async () => {
    render(
      <On>
        <Recipients />
      </On>,
    );
    await waitFor(() => expect(h.paths).toEqual([`${BASE}?page=0&pageSize=50`]));

    fireEvent.click(screen.getAllByRole('button', { name: 'Filter State' })[0]);
    const dialog = await screen.findByRole('dialog', { name: 'Filter State' });
    fireEvent.click(within(dialog).getByRole('checkbox', { name: 'Sent' }));
    fireEvent.click(within(dialog).getByRole('checkbox', { name: 'Read' }));

    await waitFor(() => expect(h.paths.at(-1)).toBe(`${BASE}?page=0&pageSize=50&state=sent%2Cread`));
    expect(new URLSearchParams(h.paths.at(-1)!.split('?')[1]).get('state')).toBe('sent,read');
  });

  it('both looks: one state still goes as the single value', async () => {
    render(
      <On>
        <Recipients />
      </On>,
    );
    await waitFor(() => expect(h.paths).toEqual([`${BASE}?page=0&pageSize=50`]));
    fireEvent.click(screen.getAllByRole('button', { name: 'Filter State' })[0]);
    const dialog = await screen.findByRole('dialog', { name: 'Filter State' });
    fireEvent.click(within(dialog).getByRole('checkbox', { name: 'Failed' }));
    await waitFor(() => expect(h.paths.at(-1)).toBe(`${BASE}?page=0&pageSize=50&state=failed`));
  });
});
