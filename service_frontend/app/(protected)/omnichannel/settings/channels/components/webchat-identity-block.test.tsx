/**
 * Plan 34 (A7b) review round 1, S6 - the allowed-origins editor on a WEBCHAT
 * channel's Configuration tab must mirror the backend permission.
 * `PUT /omnichannel/channels/{id}/widget` requires `channels.manage`, so a
 * `channels.read`-only user offered an Add/Save can only ever get a 403
 * toast (foolproof-UI: never offer an action that can only fail).
 *
 * Also pins N3: the block renders the config the PARENT already fetched -
 * the page used to GET the same record twice.
 */
import { useForm } from 'react-hook-form';
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { Form } from '@/components/ui/form';
import type { Channel, WebchatConfig } from '@/types/omnichannel';
import type { ChannelDetailValues } from './channel-schema';
import { ConfigurationTab } from './channel-form-fields';

const getConfig = vi.fn();
const save = vi.fn();
let allowed = new Set<string>(['channels.read', 'channels.manage']);

vi.mock('@/hooks/use-webchat-config', () => ({
  useWebchatConfig: (channelId: string, enabled: boolean) => {
    if (enabled) getConfig(channelId);
    return {
      config: null,
      isLoading: false,
      error: null,
      refresh: vi.fn(),
      save,
      rotateSecret: vi.fn(),
    };
  },
}));

vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({ can: (key: string) => allowed.has(key), ready: true, permissions: allowed }),
}));

vi.mock('@/hooks/use-datetime', () => ({
  useDatetime: () => ({
    formatDate: (v: string) => v,
    formatDateTime: (v: string) => v,
    timezone: 'UTC',
  }),
}));

const CONFIG: WebchatConfig = {
  widgetKey: 'wk_demo0000000000000000000001',
  allowedOrigins: ['https://shop.acme.test'],
  tokenEpoch: 0,
  appearance: {
    accentColor: '#FF5A00',
    position: 'right',
    headerTitle: 'Chat with us',
    agentDisplayName: 'Support',
  },
  greeting: 'Hi! How can we help?',
  offlineGreeting: "We're offline right now.",
  preChat: { askName: true, askEmail: true, askPhone: false },
  snippet: '<script src="https://app.example/omnichannel/widget/wk_demo.js" async></script>',
};

const CHANNEL = {
  id: 'chn-1',
  tenantId: 't-1',
  workspaceId: 'ws-1',
  channelType: 'WEBCHAT',
  name: 'Website chat',
  isActive: true,
  status: 'ACTIVE',
  isTrashed: false,
  createdAt: '2026-01-01T00:00:00Z',
  updatedAt: '2026-01-01T00:00:00Z',
} as unknown as Channel;

function Harness() {
  const form = useForm<ChannelDetailValues>({ defaultValues: {} as ChannelDetailValues });
  return (
    <Form {...form}>
      <ConfigurationTab
        form={form}
        editing={false}
        channel={CHANNEL}
        channelId="chn-1"
        onChannelSynced={vi.fn()}
        webchatConfig={CONFIG}
        onWebchatConfigSaved={vi.fn()}
      />
    </Form>
  );
}

describe('WebchatIdentityBlock (Configuration tab)', () => {
  it('offers the origins editor to a channels.manage user', () => {
    allowed = new Set(['channels.read', 'channels.manage']);
    render(<Harness />);
    expect(screen.getByText('https://shop.acme.test')).toBeInTheDocument();
    expect(screen.getByLabelText('New allowed origin')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /save origins/i })).toBeInTheDocument();
  });

  it('renders the list read-only for a channels.read-only user', () => {
    allowed = new Set(['channels.read']);
    render(<Harness />);
    expect(screen.getByText('https://shop.acme.test')).toBeInTheDocument();
    expect(screen.queryByLabelText('New allowed origin')).toBeNull();
    expect(screen.queryByRole('button', { name: /save origins/i })).toBeNull();
    expect(screen.queryByRole('button', { name: /remove https:\/\/shop\.acme\.test/i })).toBeNull();
  });

  it('never fires a second widget-config GET (N3 - the parent already did)', () => {
    allowed = new Set(['channels.read', 'channels.manage']);
    getConfig.mockClear();
    render(<Harness />);
    expect(getConfig).not.toHaveBeenCalled();
    expect(screen.getByText(CONFIG.widgetKey)).toBeInTheDocument();
  });
});
