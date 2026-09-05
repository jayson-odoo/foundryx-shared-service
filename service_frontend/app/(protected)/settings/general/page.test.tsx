/**
 * AC-DLA-42: Settings > General shows "Delete countdown (seconds)" and
 * "Reversible action countdown (seconds)" (1-60), saving reaches the
 * settings service.
 */
import { act, render, screen, waitFor } from '@testing-library/react';
import { fireEvent } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({ can: () => true, ready: true, permissions: new Set<string>() }),
}));

vi.mock('next-auth/react', () => ({
  useSession: () => ({ status: 'authenticated', data: { user: { id: 'u1', timezone: 'UTC' } } }),
  SessionProvider: ({ children }: { children: React.ReactNode }) => children,
}));

const getTenantSettings = vi.fn();
const setTenantSettings = vi.fn();
vi.mock('@/services/ems-service', () => ({
  emsService: {
    getTenantSettings: (...a: unknown[]) => getTenantSettings(...a),
    setTenantSettings: (...a: unknown[]) => setTenantSettings(...a),
  },
}));

const toastError = vi.fn();
const toastSuccess = vi.fn();
vi.mock('sonner', () => ({ toast: { error: (...a: unknown[]) => toastError(...a), success: (...a: unknown[]) => toastSuccess(...a) } }));

import { SettingsProvider } from '@/providers/settings-provider';
import GeneralSettingsPage from './page';

function renderPage() {
  return render(
    <SettingsProvider>
      <GeneralSettingsPage />
    </SettingsProvider>,
  );
}

const BASE = {
  defaultCurrency: 'USD',
  priceDecimals: 2,
  deferredDestructiveSeconds: 10,
  deferredReversibleSeconds: 5,
};

beforeEach(() => {
  vi.clearAllMocks();
  getTenantSettings.mockResolvedValue({ ...BASE });
  setTenantSettings.mockImplementation(async (patch: Partial<typeof BASE>) => ({ ...BASE, ...patch }));
});

describe('Settings > General - deferred actions grace windows', () => {
  it('renders the two countdown fields, pre-filled from the service', async () => {
    renderPage();
    await waitFor(() => expect(getTenantSettings).toHaveBeenCalled());
    const destructive = (await screen.findByDisplayValue('10')) as HTMLInputElement;
    expect(destructive).toBeTruthy();
    expect(screen.getByText('Delete countdown (seconds)')).toBeInTheDocument();
    expect(screen.getByText('Reversible action countdown (seconds)')).toBeInTheDocument();
  });

  it('rejects an out-of-range value (>60) before saving', async () => {
    renderPage();
    await waitFor(() => expect(getTenantSettings).toHaveBeenCalled());
    const destructive = await screen.findByDisplayValue('10');
    fireEvent.change(destructive, { target: { value: '99' } });

    const saveButtons = screen.getAllByRole('button', { name: 'Save settings' });
    await act(async () => {
      fireEvent.click(saveButtons[saveButtons.length - 1]);
    });

    expect(toastError).toHaveBeenCalledWith(
      'Delete countdown must be a whole number between 1 and 60.',
    );
    expect(setTenantSettings).not.toHaveBeenCalled();
  });

  it('saves valid values through emsService.setTenantSettings', async () => {
    renderPage();
    await waitFor(() => expect(getTenantSettings).toHaveBeenCalled());
    const reversible = await screen.findByDisplayValue('5');
    fireEvent.change(reversible, { target: { value: '3' } });

    const saveButtons = screen.getAllByRole('button', { name: 'Save settings' });
    await act(async () => {
      fireEvent.click(saveButtons[saveButtons.length - 1]);
    });

    expect(setTenantSettings).toHaveBeenCalledWith(
      expect.objectContaining({ deferredReversibleSeconds: 3 }),
    );
  });
});
