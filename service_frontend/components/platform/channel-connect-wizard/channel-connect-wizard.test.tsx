/**
 * Channel connect wizard - plan 32 / A7a channel-type + page-selection steps
 * (AC-CHN-01/02/03, AC-CHN-61). No Meta env in the test process, so every
 * type falls back to the simulated dialog (the same one WhatsApp already
 * uses) - the real OAuth path is covered by `use-connect-channel.test.ts`.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { Channel, Workspace } from '@/types/omnichannel';
import { ChannelConnectWizard } from './channel-connect-wizard';

const WORKSPACES: Workspace[] = [
  {
    id: 'wsp-1',
    tenantId: 'default',
    name: 'General',
    status: 'ACTIVE',
    channelCount: 0,
    memberCount: 1,
    isDefault: true,
    isTrashed: false,
    createdAt: '2026-01-01T00:00:00Z',
    updatedAt: '2026-01-01T00:00:00Z',
  },
];

vi.mock('@/services/workspace-service', () => ({
  workspaceService: {
    list: vi.fn(() => Promise.resolve({ data: WORKSPACES, total: 1, page: 0, pageSize: 100 })),
  },
}));

const CHANNEL = {
  id: 'chn-fb-9',
  name: 'Foundryx Events Co. (Messenger)',
  displayPhoneNumber: null,
  externalAccountName: 'Foundryx Events Co.',
} as Channel;

const connectMetaChannel = vi.fn();
vi.mock('@/services/onboarding-service', () => ({
  onboardingService: {
    completeOnboarding: vi.fn(),
    manualConnect: vi.fn(),
    listMetaPages: vi.fn(),
    connectMetaChannel: (...args: unknown[]) => connectMetaChannel(...args),
  },
}));

describe('ChannelConnectWizard - plan 32 / A7a channel-type step', () => {
  it('offers exactly WhatsApp, Messenger and Instagram as a searchable select', async () => {
    render(<ChannelConnectWizard open onOpenChange={vi.fn()} />);
    await waitFor(() => expect(screen.getByText('Connect a channel')).toBeInTheDocument());

    const trigger = screen.getByRole('combobox', { name: 'Channel type' });
    // Default selection is WhatsApp - the trigger already shows that label,
    // so only assert the OTHER two implemented types are offered once open.
    expect(trigger).toHaveTextContent('WhatsApp');
    fireEvent.click(trigger);
    expect(screen.getByText('Messenger')).toBeInTheDocument();
    expect(screen.getByText('Instagram')).toBeInTheDocument();
    // Foolproof-UI - no pruned/unimplemented type is ever offered.
    expect(screen.queryByText('Douyin')).not.toBeInTheDocument();
    expect(screen.queryByText('Xiaohongshu')).not.toBeInTheDocument();
  });

  it('the workspace picker is a searchable select, not a bare shadcn Select', async () => {
    render(<ChannelConnectWizard open onOpenChange={vi.fn()} />);
    await waitFor(() => expect(screen.getByRole('combobox', { name: 'Workspace' })).toBeInTheDocument());
    fireEvent.click(screen.getByRole('combobox', { name: 'Workspace' }));
    expect(screen.getByPlaceholderText('Search…')).toBeInTheDocument();
  });

  it('Messenger + no Meta app -> the simulated dialog offers a page, excluding an already-connected one', async () => {
    render(<ChannelConnectWizard open onOpenChange={vi.fn()} />);
    await waitFor(() => expect(screen.getByRole('combobox', { name: 'Channel type' })).toBeInTheDocument());

    fireEvent.click(screen.getByRole('combobox', { name: 'Channel type' }));
    fireEvent.click(screen.getByText('Messenger'));
    await waitFor(() => expect(screen.getByRole('combobox', { name: 'Channel type' })).toHaveTextContent('Messenger'));

    fireEvent.click(screen.getByRole('button', { name: /Connect \(sandbox\)/ }));

    await waitFor(() => expect(screen.getByText('Connect with Messenger')).toBeInTheDocument());
    // pg-701 is already bound to the seeded chn-fb-001 sandbox channel - not offered.
    expect(screen.queryByTestId('mock-meta-page-pg-701')).not.toBeInTheDocument();
    expect(screen.getByTestId('mock-meta-page-pg-703')).toBeInTheDocument();
  });

  it('picking a page in the simulated dialog connects the channel', async () => {
    connectMetaChannel.mockResolvedValue(CHANNEL);
    const onConnected = vi.fn();
    render(<ChannelConnectWizard open onOpenChange={vi.fn()} onConnected={onConnected} />);
    await waitFor(() => expect(screen.getByRole('combobox', { name: 'Channel type' })).toBeInTheDocument());

    fireEvent.click(screen.getByRole('combobox', { name: 'Channel type' }));
    fireEvent.click(screen.getByText('Instagram'));
    await waitFor(() => expect(screen.getByRole('combobox', { name: 'Channel type' })).toHaveTextContent('Instagram'));
    fireEvent.click(screen.getByRole('button', { name: /Connect \(sandbox\)/ }));

    await waitFor(() => expect(screen.getByTestId('mock-meta-page-pg-702')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('mock-meta-page-pg-702'));
    fireEvent.click(screen.getByTestId('mock-meta-authorize'));

    await waitFor(() => expect(screen.getByText('Sandbox channel created')).toBeInTheDocument());
    expect(connectMetaChannel).toHaveBeenCalledWith(
      expect.objectContaining({ channelType: 'INSTAGRAM', pageId: 'pg-702' }),
    );
  });

  it('WhatsApp keeps its manual-connect affordance; Messenger/Instagram do not', async () => {
    render(<ChannelConnectWizard open onOpenChange={vi.fn()} />);
    await waitFor(() => expect(screen.getByText('Set up manually (paste token)')).toBeInTheDocument());

    fireEvent.click(screen.getByRole('combobox', { name: 'Channel type' }));
    fireEvent.click(screen.getByText('Messenger'));
    await waitFor(() =>
      expect(screen.queryByText('Set up manually (paste token)')).not.toBeInTheDocument(),
    );
  });
});
