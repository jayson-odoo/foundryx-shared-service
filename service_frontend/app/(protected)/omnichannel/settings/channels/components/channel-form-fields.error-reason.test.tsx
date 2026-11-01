/**
 * Plan 42 (AC-42-23): a channel in ERROR shows the destructive badge on the
 * detail and the fixed reason "Access token expired or revoked".
 */
import { useForm } from 'react-hook-form';
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { Form } from '@/components/ui/form';
import type { Channel } from '@/types/omnichannel';
import { CHANNEL_STATUS_REGISTRY } from './channel-status';
import type { ChannelDetailValues } from './channel-schema';
import { ConfigurationTab } from './channel-form-fields';

vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({ can: () => true, ready: true, permissions: new Set<string>() }),
}));
vi.mock('@/hooks/use-datetime', () => ({
  useDatetime: () => ({ formatDate: (i: string) => String(i), formatDateTime: (i: string) => String(i) }),
}));
vi.mock('@/hooks/use-webchat-config', () => ({
  useWebchatConfig: () => ({ config: null, isLoading: false, error: null, refresh: vi.fn(), save: vi.fn(), rotateSecret: vi.fn() }),
}));
vi.mock('@/services/channel-service', () => ({ channelService: { syncConfig: vi.fn(), testConnection: vi.fn() } }));
vi.mock('@/lib/toast', () => ({ toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() } }));

const base = {
  id: 'chn-th-1',
  tenantId: 'default',
  workspaceId: 'wsp-1',
  workspaceName: 'General',
  channelType: 'WHATSAPP',
  name: 'Support Line',
  isActive: true,
  isTrashed: false,
  wabaId: 'waba-th-1',
  phoneNumberId: 'pn-th-1',
  displayPhoneNumber: '+60 11-111 0042',
  businessAccountName: null,
  verifiedName: null,
  lastVerifiedAt: null,
  profileSyncedAt: null,
  createdAt: '2026-01-01T00:00:00Z',
  updatedAt: '2026-01-01T00:00:00Z',
};

function Wrapper({ channel }: { channel: Channel }) {
  const form = useForm<ChannelDetailValues>({ defaultValues: { name: channel.name, isActive: channel.isActive } });
  return (
    <Form {...form}>
      <ConfigurationTab
        form={form}
        editing={false}
        channel={channel}
        channelId={channel.id}
        onChannelSynced={vi.fn()}
        webchatConfig={null}
        onWebchatConfigSaved={vi.fn()}
      />
    </Form>
  );
}

describe('ConfigurationTab status reason - AC-42-23', () => {
  it('the Error status uses the destructive badge (existing registry)', () => {
    expect(CHANNEL_STATUS_REGISTRY.ERROR.tone).toBe('destructive');
  });

  it('control: an Active channel shows its badge and no reason', () => {
    render(<Wrapper channel={{ ...base, status: 'ACTIVE' } as Channel} />);
    expect(screen.getAllByText('Active').length).toBeGreaterThan(0);
    expect(screen.queryByText('Access token expired or revoked')).not.toBeInTheDocument();
  });

  it('an Error channel shows the badge and the fixed reason', () => {
    render(<Wrapper channel={{ ...base, status: 'ERROR' } as Channel} />);
    expect(screen.getAllByText('Error').length).toBeGreaterThan(0);
    expect(screen.getByText('Access token expired or revoked')).toBeInTheDocument();
  });
});
