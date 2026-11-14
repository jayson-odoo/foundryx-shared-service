/**
 * AC-43-40: the API Keys tab shows each key's webhook endpoint count. Revoke on
 * a key with endpoints opens a dialog naming the count with "Also pause them"
 * (on by default); confirm parks `api_keys.revoke` with the choice. A key with
 * none parks directly, as before.
 */
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ApiKeyItem } from '@/types/api-keys';
import {
  __resetApiKeysMock,
  mockApiKeysService,
} from '@/services/api-keys-service.mock';
import { ApiKeysTab } from './workspace-api-keys-tab';

type KeyRow = ApiKeyItem & { webhookEndpointCount: number };

const list = vi.fn();
const park = vi.fn();

vi.mock('@/services/api-keys-service', () => ({
  apiKeysService: {
    list: (...a: unknown[]) => list(...a),
    mint: vi.fn(),
    revoke: vi.fn(),
  },
}));

vi.mock('@/services/pending-actions-service', () => ({
  pendingActionsService: {
    park: (...a: unknown[]) => park(...a),
    cancel: vi.fn(),
    current: vi.fn().mockResolvedValue({ pending: null }),
  },
}));

vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({ can: () => true, ready: true, permissions: new Set<string>() }),
}));

vi.mock('@/lib/toast', () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn(), dismiss: vi.fn() },
}));
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn(), dismiss: vi.fn() } }));

vi.mock('next-auth/react', () => ({
  useSession: () => ({ data: { user: { permissions: [] } }, status: 'authenticated' }),
  getSession: vi.fn().mockResolvedValue(null),
  signOut: vi.fn(),
}));

vi.mock('@/hooks/use-datetime', () => ({
  useDatetime: () => ({ formatDate: () => 'Jul', formatDateTime: () => 'Jul' }),
}));

function key(over: Partial<KeyRow>): KeyRow {
  return {
    id: 'key-x',
    workspaceId: 'wsp-001',
    name: 'Key',
    keyPrefix: 'abcdefgh',
    maskedKey: 'fxw_live_abcdefgh....',
    status: 'ACTIVE',
    lastUsedAt: null,
    revokedAt: null,
    createdAt: '2026-07-04T00:00:00Z',
    webhookEndpointCount: 0,
    ...over,
  };
}

const WITH = key({ id: 'key-with', name: 'Order sync', webhookEndpointCount: 3 });
const NONE = key({ id: 'key-none', name: 'Reports', webhookEndpointCount: 0 });

beforeEach(() => {
  vi.clearAllMocks();
  list.mockResolvedValue([WITH, NONE]);
  park.mockResolvedValue({
    id: 'pa-1',
    status: 'pending',
    commitAt: new Date(Date.now() + 10_000).toISOString(),
    windowSeconds: 10,
  });
});

async function rowFor(name: string): Promise<HTMLElement> {
  const cell = await screen.findByText(name);
  const tr = cell.closest('tr');
  if (!tr) throw new Error(`no table row for ${name}`);
  return tr as HTMLElement;
}

async function clickRevoke(name: string) {
  const tr = await rowFor(name);
  await userEvent.click(within(tr).getByRole('button', { name: /actions/i }));
  await userEvent.click(await screen.findByRole('menuitem', { name: 'Revoke' }));
}

function renderTab() {
  return render(<ApiKeysTab workspaceId="wsp-001" creating={false} />);
}

describe('AC-43-40 endpoint count on the key list', () => {
  it('AC-43-40: a key with 3 webhook endpoints shows 3 in its row', async () => {
    renderTab();
    const tr = await rowFor('Order sync');
    expect(within(tr).getByText(/\b3\b/)).toBeInTheDocument();
  });

  it('AC-43-40 (control): a key with 0 endpoints does not show 3', async () => {
    renderTab();
    const tr = await rowFor('Reports');
    expect(within(tr).queryByText(/\b3\b/)).not.toBeInTheDocument();
  });
});

describe('AC-43-40 revoke on a key with no endpoints', () => {
  it('AC-43-40: opens no dialog and parks api_keys.revoke for that key', async () => {
    renderTab();
    await clickRevoke('Reports');
    await waitFor(() => expect(park).toHaveBeenCalledTimes(1));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(park).toHaveBeenCalledWith(
      'api_keys.revoke',
      'api_key',
      'key-none',
      undefined,
    );
  });
});

describe('AC-43-40 revoke on a key with 3 endpoints', () => {
  it('AC-43-40: opens a dialog naming 3 with "Also pause them" on, and parks nothing yet', async () => {
    renderTab();
    await clickRevoke('Order sync');
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText(/\b3\b/)).toBeInTheDocument();
    expect(within(dialog).getByLabelText(/also pause them/i)).toBeChecked();
    expect(park).not.toHaveBeenCalled();
  });

  it('AC-43-40: confirm with the default parks api_keys.revoke with pauseEndpoints true', async () => {
    renderTab();
    await clickRevoke('Order sync');
    const dialog = await screen.findByRole('dialog');
    await userEvent.click(within(dialog).getByRole('button', { name: /revoke/i }));
    await waitFor(() => expect(park).toHaveBeenCalledTimes(1));
    expect(park).toHaveBeenCalledWith(
      'api_keys.revoke',
      'api_key',
      'key-with',
      expect.objectContaining({ pauseEndpoints: true }),
    );
  });

  it('AC-43-40: switching "Also pause them" off then confirming parks pauseEndpoints false', async () => {
    renderTab();
    await clickRevoke('Order sync');
    const dialog = await screen.findByRole('dialog');
    const toggle = within(dialog).getByLabelText(/also pause them/i);
    await userEvent.click(toggle);
    expect(toggle).not.toBeChecked();
    await userEvent.click(within(dialog).getByRole('button', { name: /revoke/i }));
    await waitFor(() => expect(park).toHaveBeenCalledTimes(1));
    expect(park).toHaveBeenCalledWith(
      'api_keys.revoke',
      'api_key',
      'key-with',
      expect.objectContaining({ pauseEndpoints: false }),
    );
  });

  it('AC-43-40: Cancel closes the dialog and parks nothing', async () => {
    renderTab();
    await clickRevoke('Order sync');
    const dialog = await screen.findByRole('dialog');
    await userEvent.click(within(dialog).getByRole('button', { name: /cancel/i }));
    await waitFor(() =>
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument(),
    );
    expect(park).not.toHaveBeenCalled();
  });

  it('AC-43-40: the dialog has an accessible description and no instructional copy', async () => {
    renderTab();
    await clickRevoke('Order sync');
    const dialog = await screen.findByRole('dialog');
    expect(dialog).toHaveAccessibleDescription();
    expect(dialog.textContent ?? '').not.toMatch(
      /irreversible|cannot be undone|you can|you may|please|note that|make sure|this will|should/i,
    );
  });
});

describe('AC-43-40 mock service', () => {
  beforeEach(() => __resetApiKeysMock());

  it('AC-43-40: a key from the mock list carries a numeric webhookEndpointCount', async () => {
    const { key: minted } = await mockApiKeysService.mint('wsp-mock', 'Mock key');
    const rows = (await mockApiKeysService.list('wsp-mock')) as KeyRow[];
    expect(rows.find((r) => r.id === minted.id)).toBeDefined();
    for (const r of rows) expect(typeof r.webhookEndpointCount).toBe('number');
  });
});
