/**
 * AC-43-41: the workspace form has a Webhooks tab gated by `webhooks.read`,
 * listing the rows of the workspace (per-channel and all-channels) from the workspace route with no Add button and
 * the same row actions as the channel tab. Both webhook lists show "Registered
 * by" with the key's name on a key's row and nothing on a staff row.
 */
import { render, renderHook, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactNode } from 'react';
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import type { WebhookEndpoint } from '@/types/whatsapp-webhook';
import { mockWhatsappWebhookService } from '@/services/whatsapp-webhook-service.mock';
import { ChannelWebhooksTab } from '../../channels/components/channel-webhooks-tab';
import type { useWorkspaceForm as UseWorkspaceForm } from './use-workspace-form';

type Row = WebhookEndpoint & { registeredByKeyName: string | null };

let can: (key: string) => boolean = () => true;
vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({
    can: (key: string) => can(key),
    ready: true,
    permissions: new Set<string>(),
  }),
}));

const apiFetch = vi.fn();
vi.mock('@/lib/api-client', async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  apiFetch: (...a: unknown[]) => apiFetch(...a),
}));

const park = vi.fn();
vi.mock('@/services/pending-actions-service', () => ({
  pendingActionsService: {
    park: (...a: unknown[]) => park(...a),
    cancel: vi.fn(),
    current: vi.fn().mockResolvedValue({ pending: null }),
  },
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

vi.mock('@/services/workspace-service', () => ({
  workspaceService: {
    get: vi.fn(async () => ({
      id: 'wsp-1',
      tenantId: 'ten-1',
      name: 'General',
      status: 'ACTIVE',
      channelCount: 0,
      memberCount: 0,
      isDefault: false,
      isTrashed: false,
      createdAt: '2026-01-01T00:00:00Z',
      updatedAt: '2026-01-01T00:00:00Z',
    })),
    update: vi.fn(),
    trash: vi.fn(),
    restore: vi.fn(),
  },
}));

let useWorkspaceForm: typeof UseWorkspaceForm;
beforeAll(async () => {
  ({ useWorkspaceForm } = await import('./use-workspace-form'));
});

function row(over: Partial<Row>): Row {
  return {
    id: 'wh-x',
    tenantId: 'tnt-001',
    workspaceId: 'wsp-1',
    channelId: null,
    name: 'Row',
    url: 'https://hooks.example.com/x',
    events: ['message.inbound'],
    status: 'ACTIVE',
    consecutiveFailures: 0,
    lastSuccessAt: null,
    disabledAt: null,
    disabledReason: null,
    createdAt: '2026-07-04T00:00:00Z',
    updatedAt: '2026-07-04T00:00:00Z',
    registeredByKeyName: null,
    ...over,
  };
}

const BY_KEY = row({ id: 'wh-key', name: 'Order feed', registeredByKeyName: 'Order sync key' });
const BY_STAFF = row({ id: 'wh-staff', name: 'Staff feed', registeredByKeyName: null });

beforeEach(() => {
  vi.clearAllMocks();
  can = () => true;
  apiFetch.mockImplementation(async (path: string) => {
    if (path.includes('/webhooks')) return { data: [BY_KEY, BY_STAFF] };
    return { data: [] };
  });
  park.mockResolvedValue({
    id: 'pa-1',
    status: 'pending',
    commitAt: new Date(Date.now() + 10_000).toISOString(),
    windowSeconds: 10,
  });
});

async function webhooksTab() {
  const { result } = renderHook(() => useWorkspaceForm('wsp-1', false));
  await waitFor(() => expect(result.current.isLoading).toBe(false));
  return result.current.config!.tabs.find((t) => t.id === 'webhooks');
}

async function rowFor(name: string): Promise<HTMLElement> {
  const cell = await screen.findByText(name);
  const tr = cell.closest('tr');
  if (!tr) throw new Error(`no table row for ${name}`);
  return tr as HTMLElement;
}

async function renderWorkspaceTab() {
  const tab = await webhooksTab();
  if (!tab) throw new Error('no Webhooks tab');
  return render(<>{tab.render({ editing: false }) as ReactNode}</>);
}

describe('AC-43-41 Webhooks tab gating', () => {
  it('AC-43-41: the tab is present, labelled Webhooks, with webhooks.read', async () => {
    can = (k) => k === 'webhooks.read';
    const tab = await webhooksTab();
    expect(tab?.label).toBe('Webhooks');
  });

  it('AC-43-41: the tab is absent without webhooks.read', async () => {
    can = (k) => k !== 'webhooks.read';
    expect(await webhooksTab()).toBeUndefined();
  });

  it('AC-43-41: the tab is absent while creating a workspace', async () => {
    can = () => true;
    const { result } = renderHook(() => useWorkspaceForm(undefined, true));
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.config!.tabs.find((t) => t.id === 'webhooks')).toBeUndefined();
  });
});

describe('AC-43-41 workspace Webhooks list', () => {
  it('AC-43-41: lists the rows from the workspace webhooks route', async () => {
    await renderWorkspaceTab();
    expect(await screen.findByText('Order feed')).toBeInTheDocument();
    expect(screen.getByText('Staff feed')).toBeInTheDocument();
    const paths = apiFetch.mock.calls.map((c) => String(c[0]));
    expect(paths).toContain('/omnichannel/workspaces/wsp-1/webhooks');
  });

  it('AC-43-41: has no Add button', async () => {
    await renderWorkspaceTab();
    await screen.findByText('Order feed');
    expect(screen.queryByRole('button', { name: /add/i })).not.toBeInTheDocument();
  });

  it('AC-43-41: a row offers the same actions as on the channel tab', async () => {
    await renderWorkspaceTab();
    const tr = await rowFor('Order feed');
    await userEvent.click(within(tr).getByRole('button', { name: /actions/i }));
    for (const label of ['Edit', 'Rotate secret', 'Disable', 'View deliveries', 'Delete']) {
      expect(await screen.findByRole('menuitem', { name: label })).toBeInTheDocument();
    }
  });

  it('AC-43-41: Delete on a row parks webhooks.delete for that row id', async () => {
    await renderWorkspaceTab();
    const tr = await rowFor('Order feed');
    await userEvent.click(within(tr).getByRole('button', { name: /actions/i }));
    await userEvent.click(await screen.findByRole('menuitem', { name: 'Delete' }));
    await waitFor(() => expect(park).toHaveBeenCalledTimes(1));
    expect(park).toHaveBeenCalledWith('webhooks.delete', 'webhook_endpoint', 'wh-key', undefined);
  });
});

const PER_CHANNEL = row({ id: 'wh-chan', name: 'Channel feed', channelId: 'chn-1' });
const PAUSED_BY_REVOKE = row({
  id: 'wh-revoked',
  name: 'Paused feed',
  status: 'DISABLED',
  disabledAt: '2026-07-05T00:00:00Z',
  disabledReason: 'The API key that registered it was revoked.',
});
const PAUSED_BY_STAFF = row({
  id: 'wh-user',
  name: 'Stopped feed',
  status: 'DISABLED',
  disabledAt: '2026-07-05T00:00:00Z',
  disabledReason: 'Disabled by user.',
});

describe('AC-43-41 per-channel rows and the paused reason', () => {
  it('AC-43-41: control, a per-channel row is listed on the workspace tab with no "All channels" label, an all-channels row keeps it', async () => {
    apiFetch.mockImplementation(async () => ({ data: [BY_KEY, PER_CHANNEL] }));
    await renderWorkspaceTab();
    const chan = await rowFor('Channel feed');
    const all = await rowFor('Order feed');
    expect(within(all).getByText('All channels')).toBeInTheDocument(); // control
    expect(within(chan).queryByText('All channels')).not.toBeInTheDocument();
  });

  it('AC-43-41: a row paused by a revoke shows why', async () => {
    apiFetch.mockImplementation(async () => ({ data: [PAUSED_BY_REVOKE] }));
    await renderWorkspaceTab();
    const tr = await rowFor('Paused feed');
    expect(within(tr).getByText('The API key that registered it was revoked.')).toBeInTheDocument();
  });

  it('AC-43-41: control, an auto-disabled row shows its reason', async () => {
    apiFetch.mockImplementation(async () => ({
      data: [{ ...PAUSED_BY_REVOKE, id: 'wh-auto', name: 'Auto feed', status: 'AUTO_DISABLED', disabledReason: 'Too many failures.' }],
    }));
    await renderWorkspaceTab();
    const tr = await rowFor('Auto feed');
    expect(within(tr).getByText('Too many failures.')).toBeInTheDocument();
  });

  it('AC-43-41: control, a row a staff user disabled shows no reason text, as today', async () => {
    apiFetch.mockImplementation(async () => ({ data: [PAUSED_BY_STAFF] }));
    await renderWorkspaceTab();
    const tr = await rowFor('Stopped feed');
    expect(within(tr).queryByText('Disabled by user.')).not.toBeInTheDocument();
  });
});

describe('AC-43-41 Registered by', () => {
  it('AC-43-41: the workspace list has a "Registered by" column showing the key name on a key row', async () => {
    await renderWorkspaceTab();
    const tr = await rowFor('Order feed');
    expect(screen.getByText('Registered by')).toBeInTheDocument();
    expect(within(tr).getByText('Order sync key')).toBeInTheDocument();
  });

  it('AC-43-41: a staff row (registeredByKeyName null) shows no key name and no placeholder wording', async () => {
    await renderWorkspaceTab();
    const tr = await rowFor('Staff feed');
    expect(within(tr).queryByText('Order sync key')).not.toBeInTheDocument();
    expect(within(tr).queryByText(/unknown|deleted|api key|null/i)).not.toBeInTheDocument();
  });

  it('AC-43-41: the channel Webhooks tab shows "Registered by" with the key name on a key row', async () => {
    render(<ChannelWebhooksTab channelId="chn-001" />);
    const tr = await rowFor('Order feed');
    expect(screen.getByText('Registered by')).toBeInTheDocument();
    expect(within(tr).getByText('Order sync key')).toBeInTheDocument();
    const staff = await rowFor('Staff feed');
    expect(within(staff).queryByText('Order sync key')).not.toBeInTheDocument();
    expect(within(staff).queryByText(/unknown|deleted|api key|null/i)).not.toBeInTheDocument();
  });
});

describe('AC-43-41 mock service', () => {
  it('AC-43-41: the mock webhook list carries registeredByKeyName, a key name on at least one row and null on at least one', async () => {
    const rows = (await mockWhatsappWebhookService.list('chn-mock-1')) as Row[];
    for (const r of rows) expect('registeredByKeyName' in r).toBe(true);
    expect(rows.some((r) => typeof r.registeredByKeyName === 'string')).toBe(true);
    expect(rows.some((r) => r.registeredByKeyName === null)).toBe(true);
  });
});
