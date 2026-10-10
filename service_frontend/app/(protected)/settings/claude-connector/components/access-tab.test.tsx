import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ApiError } from '@/lib/api-client';
import { AccessTab } from './access-tab';

const canKeys: string[] = ['connector.read', 'connector.settings'];
vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({ can: (k: string) => canKeys.includes(k), ready: true, permissions: new Set(canKeys) }),
}));
const getTenantSettings = vi.fn();
const updateTenantSettings = vi.fn();
const listSettingsAudit = vi.fn();
vi.mock('@/services/connector-service', () => ({
  getTenantSettings: (...a: unknown[]) => getTenantSettings(...a),
  updateTenantSettings: (...a: unknown[]) => updateTenantSettings(...a),
  listSettingsAudit: (...a: unknown[]) => listSettingsAudit(...a),
}));
vi.mock('@/hooks/use-datetime', () => ({
  useDatetime: () => ({ formatDate: (s: string) => s, formatDateTime: (s: string) => `DT:${s}` }),
}));
const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
vi.mock('@/lib/toast', () => ({ toast }));

const settings = (over: Record<string, unknown> = {}) => ({
  publicBaseUrl: { value: 'https://ss.test', source: 'default' },
  allowedClientCidrs: { value: '160.79.104.0/21', source: 'environment' },
  redirectAllowlist: { value: 'https://claude.ai/api/mcp/auth_callback', source: 'default' },
  manifestTtlSeconds: { value: '900', source: 'default' },
  callTimeoutSeconds: { value: '15', source: 'default' },
  callLogRetentionDays: { value: '180', source: 'default' },
  forwardedForWarning: true,
  ...over,
});

beforeEach(() => {
  vi.clearAllMocks();
  canKeys.splice(0, canKeys.length, 'connector.read', 'connector.settings');
  getTenantSettings.mockResolvedValue(settings());
  listSettingsAudit.mockResolvedValue([
    { id: 'a1', target: 'product:acme', action: 'updated', fields: ['ssToProductSecret'],
      actorUserId: 'u1', actorName: 'Demo Admin', at: '2026-10-10T00:00:00Z' },
  ]);
});

describe('AccessTab (SETTINGS-IN-DB-SS)', () => {
  it('shows effective values with their source and the #118 warning', async () => {
    render(<AccessTab />);
    await screen.findByText('https://ss.test');
    expect(screen.getAllByText('Default').length).toBeGreaterThan(0);
    expect(screen.getByText('Environment')).toBeTruthy();
    expect(screen.getByTestId('xff-warning')).toBeTruthy();
    expect(screen.getByText(/Product acme updated: Secret to product/)).toBeTruthy();
    expect(screen.queryAllByRole('textbox').length).toBe(0);
  });

  it('no warning once the X-Forwarded-For fix ships', async () => {
    getTenantSettings.mockResolvedValue(settings({ forwardedForWarning: false }));
    render(<AccessTab />);
    await screen.findByText('https://ss.test');
    expect(screen.queryByTestId('xff-warning')).toBeNull();
  });

  it('read-only users get no Edit button', async () => {
    canKeys.splice(0, canKeys.length, 'connector.read');
    render(<AccessTab />);
    await screen.findByText('https://ss.test');
    expect(screen.queryByRole('button', { name: /edit/i })).toBeNull();
  });

  it('saves edits, blank fields clear back to the fallback', async () => {
    updateTenantSettings.mockResolvedValue(
      settings({ callTimeoutSeconds: { value: '30', source: 'database' } }),
    );
    render(<AccessTab />);
    await screen.findByText('https://ss.test');
    await userEvent.click(screen.getByRole('button', { name: /edit/i }));
    await userEvent.type(screen.getByLabelText('Call timeout (seconds)'), '30');
    await userEvent.click(screen.getByRole('button', { name: /save/i }));
    await waitFor(() => expect(updateTenantSettings).toHaveBeenCalled());
    expect(updateTenantSettings.mock.calls[0][0]).toMatchObject({
      callTimeoutSeconds: 30,
      publicBaseUrl: null,
      allowedClientCidrs: null,
    });
    await screen.findByText('30');
    expect(toast.success).toHaveBeenCalledWith('Settings saved. Changes apply immediately.');
  });

  it('server 422 shows inline and keeps the form editable', async () => {
    updateTenantSettings.mockRejectedValue(
      new ApiError('bad', 422, null, { fieldErrors: { allowedClientCidrs: "'x' is not an IP address or CIDR range." } }),
    );
    render(<AccessTab />);
    await screen.findByText('https://ss.test');
    await userEvent.click(screen.getByRole('button', { name: /edit/i }));
    await userEvent.type(screen.getByLabelText('Allowed client IP ranges'), 'x');
    await userEvent.click(screen.getByRole('button', { name: /save/i }));
    await screen.findByText(/is not an IP address/);
    expect(screen.getByRole('button', { name: /save/i })).not.toHaveProperty('disabled', true);
  });

  it('load failure offers Retry instead of a stuck spinner', async () => {
    getTenantSettings.mockRejectedValueOnce(new Error('down'));
    render(<AccessTab />);
    await userEvent.click(await screen.findByRole('button', { name: /retry/i }));
    await screen.findByText('https://ss.test');
  });
});
