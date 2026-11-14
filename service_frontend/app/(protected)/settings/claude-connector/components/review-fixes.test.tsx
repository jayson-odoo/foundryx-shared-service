import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, renderHook, screen, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ActionMenu } from '@/components/platform/resource-actions/action-menu';
import { BulkActions } from '@/components/platform/resource-actions/bulk-actions';

const canKeys: string[] = ['connector.read', 'connector.manage'];
vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({ can: (k: string) => canKeys.includes(k), ready: true, permissions: new Set(canKeys) }),
}));
const listProducts = vi.fn();
const refreshManifest = vi.fn();
const bulkRevokeGrants = vi.fn();
const revokeGrant = vi.fn();
vi.mock('@/services/connector-service', () => ({
  listProducts: (...a: unknown[]) => listProducts(...a),
  refreshManifest: (...a: unknown[]) => refreshManifest(...a),
  bulkRevokeGrants: (...a: unknown[]) => bulkRevokeGrants(...a),
  revokeGrant: (...a: unknown[]) => revokeGrant(...a),
  listGrants: vi.fn(),
}));
const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
vi.mock('@/lib/toast', () => ({ toast }));
vi.mock('sonner', () => ({ toast }));
vi.mock('@/hooks/use-datetime', () => ({
  useDatetime: () => ({ formatDate: (s: string) => s, formatDateTime: (s: string) => `DT:${s}` }),
}));

import { ProductsTab } from './products-tab';
import { useConnectorGrantListConfig } from './use-connector-grant-list-config';

const prod = (over: Record<string, unknown> = {}) => ({
  key: 'acme', mcpUrl: 'https://ss.test/mcp/acme', consentUrl: 'https://acme.test/connect/claude',
  apiBase: 'https://acme.test', manifestVersion: 'v1', toolCount: 3, fetchedAt: '2026-10-08T00:00:00Z',
  stale: false, lastError: null, secrets: { productToSs: 'set', ssToProduct: 'set' }, ...over,
});

beforeEach(() => {
  vi.clearAllMocks();
  canKeys.splice(0, canKeys.length, 'connector.read', 'connector.manage');
});

describe('review fix 6: refresh that comes back stale', () => {
  it('shows an error toast with lastError, not "Manifest refreshed."', async () => {
    listProducts.mockResolvedValue([prod()]);
    refreshManifest.mockResolvedValue(prod({ stale: true, lastError: 'upstream_error 503' }));
    render(<ProductsTab />);
    await screen.findByText('https://ss.test/mcp/acme');
    await userEvent.click(screen.getByRole('button', { name: /refresh manifest/i }));
    await vi.waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(String(toast.error.mock.calls[0][0])).toContain('upstream_error 503');
    expect(toast.success).not.toHaveBeenCalledWith('Manifest refreshed.');
  });
});

describe('review fix 8: revoke toasts use the backend result', () => {
  it('bulk revoke success toast shows the returned revoked count', async () => {
    const config = renderHook(() => useConnectorGrantListConfig()).result.current;
    const bulk = config.actions.find((a) => a.id === 'revoke-bulk')!;
    bulkRevokeGrants.mockResolvedValue({ revoked: 1 });
    const rows = [
      { id: 'a', status: 'active' }, { id: 'b', status: 'active' }, { id: 'c', status: 'active' },
    ] as never[];
    await act(async () => {
      await (bulk as { run: (r: unknown[], rt: unknown) => Promise<void> }).run(rows, { reload: vi.fn() });
    });
    expect(bulkRevokeGrants).toHaveBeenCalledWith(['a', 'b', 'c']);
    expect(toast.success).toHaveBeenCalled();
    const msg = String(toast.success.mock.calls[0][0]);
    expect(msg).toMatch(/\b1\b/);
    expect(msg).not.toMatch(/\b3\b/);
  });

  it('single revoke tolerates the {ok:true} result', async () => {
    const config = renderHook(() => useConnectorGrantListConfig()).result.current;
    const one = config.actions.find((a) => a.id === 'revoke')!;
    revokeGrant.mockResolvedValue({ ok: true });
    await act(async () => {
      await (one as { run: (r: unknown[], rt: unknown) => Promise<void> }).run(
        [{ id: 'a', status: 'active' }], { reload: vi.fn() });
    });
    expect(revokeGrant).toHaveBeenCalledWith('a');
    expect(toast.success).toHaveBeenCalled();
    expect(toast.error).not.toHaveBeenCalled();
  });
});
void ActionMenu; void BulkActions;
