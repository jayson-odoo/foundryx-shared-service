/**
 * AC-38-98: an all-channels webhook endpoint (`channelId: null`) shows on a
 * channel's Webhooks tab with an "All channels" label, keeps every row action,
 * and the Add endpoint dialog still creates a per-channel endpoint.
 */
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { WebhookEndpoint } from '@/types/whatsapp-webhook';
import { mockWhatsappWebhookService } from '@/services/whatsapp-webhook-service.mock';
import { ChannelWebhooksTab } from './channel-webhooks-tab';
import { WebhookEndpointDialog } from './webhook-endpoint-dialog';

const list = vi.fn();
const create = vi.fn();
const park = vi.fn();

vi.mock('@/services/whatsapp-webhook-service', () => ({
  whatsappWebhookService: {
    list: (...a: unknown[]) => list(...a),
    create: (...a: unknown[]) => create(...a),
    update: vi.fn(),
    rotate: vi.fn(),
    enable: vi.fn(),
    disable: vi.fn(),
    remove: vi.fn(),
    deliveries: vi.fn().mockResolvedValue([]),
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
  useCan: () => ({
    can: () => true,
    ready: true,
    permissions: new Set<string>(),
  }),
}));

vi.mock('@/lib/toast', () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

vi.mock('next-auth/react', () => ({
  useSession: () => ({ data: { user: { permissions: [] } }, status: 'authenticated' }),
  getSession: vi.fn().mockResolvedValue(null),
  signOut: vi.fn(),
}));

vi.mock('@/hooks/use-datetime', () => ({
  useDatetime: () => ({ formatDateTime: (v: string) => v }),
}));

vi.mock('@/components/platform/multi-select', () => ({
  MultiSelect: ({
    options,
    value,
    onChange,
  }: {
    options: { label: string; value: string }[];
    value: string[];
    onChange: (v: string[]) => void;
  }) => (
    <div>
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          onClick={() =>
            onChange(
              value.includes(o.value)
                ? value.filter((x) => x !== o.value)
                : [...value, o.value],
            )
          }
        >
          {`toggle ${o.label}`}
        </button>
      ))}
    </div>
  ),
}));

type Row = Omit<WebhookEndpoint, 'channelId'> & { channelId: string | null };

function row(over: Partial<Row>): WebhookEndpoint {
  const base: Row = {
    id: 'wh-x',
    tenantId: 'tnt-001',
    workspaceId: 'wsp-001',
    channelId: 'chn-001',
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
    ...over,
  };
  return base as unknown as WebhookEndpoint;
}

const ALL = row({ id: 'wh-all', name: 'Workspace feed', channelId: null });
const PER = row({ id: 'wh-per', name: 'Channel feed', channelId: 'chn-001' });

beforeEach(() => {
  vi.clearAllMocks();
  list.mockResolvedValue([ALL, PER]);
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

async function openActions(name: string) {
  const tr = await rowFor(name);
  await userEvent.click(within(tr).getByRole('button', { name: /actions/i }));
}

describe('AC-38-98 All channels label', () => {
  it('AC-38-98: a channelId null row shows "All channels" beside its name', async () => {
    render(<ChannelWebhooksTab channelId="chn-001" />);
    const tr = await rowFor('Workspace feed');
    expect(within(tr).getByText('All channels')).toBeInTheDocument();
  });

  it('AC-38-98 (control): a row with a channel id does not show "All channels"', async () => {
    render(<ChannelWebhooksTab channelId="chn-001" />);
    const tr = await rowFor('Channel feed');
    expect(within(tr).queryByText('All channels')).not.toBeInTheDocument();
  });

  it('AC-38-98: an all-channels row offers the same actions as a per-channel row', async () => {
    render(<ChannelWebhooksTab channelId="chn-001" />);
    const expected = [
      'Edit',
      'Rotate secret',
      'Disable',
      'View deliveries',
      'Delete',
    ];

    await openActions('Channel feed');
    for (const label of expected) {
      expect(
        await screen.findByRole('menuitem', { name: label }),
      ).toBeInTheDocument();
    }
    fireEvent.keyDown(document.activeElement ?? document.body, {
      key: 'Escape',
    });
    await waitFor(() =>
      expect(screen.queryByRole('menuitem')).not.toBeInTheDocument(),
    );

    await openActions('Workspace feed');
    for (const label of expected) {
      expect(
        await screen.findByRole('menuitem', { name: label }),
      ).toBeInTheDocument();
    }
  });

  it('AC-38-98: Delete on an all-channels row parks the delete for that row id', async () => {
    render(<ChannelWebhooksTab channelId="chn-001" />);
    await openActions('Workspace feed');
    await userEvent.click(
      await screen.findByRole('menuitem', { name: 'Delete' }),
    );
    await waitFor(() => expect(park).toHaveBeenCalledTimes(1));
    expect(park).toHaveBeenCalledWith(
      'webhooks.delete',
      'webhook_endpoint',
      'wh-all',
      undefined,
    );
  });

  it('AC-38-98 (control): the Add endpoint dialog creates with the channel id, no scope choice', async () => {
    create.mockResolvedValue({
      endpoint: PER,
      signingSecret: 'whsec_ABCDEF1234567890abcdef',
    });
    render(
      <WebhookEndpointDialog
        channelId="chn-001"
        endpoint={null}
        open
        onOpenChange={() => {}}
        onSaved={() => {}}
      />,
    );
    expect(screen.queryByText(/all channels/i)).not.toBeInTheDocument();
    expect(screen.queryByRole('radio')).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/name/i), {
      target: { value: 'CRM sync' },
    });
    fireEvent.change(screen.getByLabelText(/endpoint url/i), {
      target: { value: 'https://hooks.example.com/whatsapp' },
    });
    fireEvent.click(
      screen.getByRole('button', { name: /toggle inbound messages/i }),
    );
    fireEvent.click(screen.getByRole('button', { name: /add endpoint/i }));
    await waitFor(() => expect(create).toHaveBeenCalledTimes(1));
    expect(create.mock.calls[0][0]).toBe('chn-001');
  });

  it('AC-38-98: the mock service includes an all-channels row with channelId null', async () => {
    const rows = await mockWhatsappWebhookService.list('chn-mock-1');
    const allRows = rows.filter((r) => (r.channelId as string | null) === null);
    expect(allRows.length).toBeGreaterThanOrEqual(1);
  });
});
