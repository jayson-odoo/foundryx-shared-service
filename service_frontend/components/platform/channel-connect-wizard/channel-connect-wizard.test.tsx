/**
 * Channel connect wizard - plan 32 / A7a channel-type + page-selection steps
 * (AC-CHN-01/02/03, AC-CHN-61). No Meta env in the test process, so
 * Messenger/Instagram "Connect (sandbox)" reuses the REAL two-call flow
 * (`listMetaPages` then `connectMetaChannel`) against a dev-safe backend
 * stub, landing on the wizard's OWN page-selection step (never a parallel
 * mock page list) - WhatsApp alone still uses the simulated WABA-number
 * dialog, covered separately below.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { Channel, MetaPageOption, Workspace } from '@/types/omnichannel';
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

const PAGES: MetaPageOption[] = [
  // pg-701 is already bound to a live channel elsewhere - never offered.
  { id: 'pg-701', name: 'Foundryx Events Co.', connected: true, igAccountId: 'ig-701', igUsername: 'foundryx.events' },
  { id: 'pg-702', name: 'Foundryx Concierge', connected: false, igAccountId: 'ig-702', igUsername: 'foundryx.concierge' },
  { id: 'pg-703', name: 'Foundryx VIP Desk', connected: false },
];

const listMetaPages = vi.fn();
const connectMetaChannel = vi.fn();
vi.mock('@/services/onboarding-service', () => ({
  onboardingService: {
    completeOnboarding: vi.fn(),
    manualConnect: vi.fn(),
    listMetaPages: (...args: unknown[]) => listMetaPages(...args),
    connectMetaChannel: (...args: unknown[]) => connectMetaChannel(...args),
  },
}));

const webchatConnect = vi.fn();
vi.mock('@/services/webchat-service', () => ({
  webchatService: {
    connect: (...args: unknown[]) => webchatConnect(...args),
  },
}));

describe('ChannelConnectWizard - plan 32 / A7a channel-type step', () => {
  it('offers exactly WhatsApp, Messenger, Instagram and Web chat as a searchable select (AC-WEB-01)', async () => {
    render(<ChannelConnectWizard open onOpenChange={vi.fn()} />);
    await waitFor(() => expect(screen.getByText('Connect a channel')).toBeInTheDocument());

    const trigger = screen.getByRole('combobox', { name: 'Channel type' });
    // Default selection is WhatsApp - the trigger already shows that label,
    // so only assert the OTHER implemented types are offered once open.
    expect(trigger).toHaveTextContent('WhatsApp');
    fireEvent.click(trigger);
    expect(screen.getByText('Messenger')).toBeInTheDocument();
    expect(screen.getByText('Instagram')).toBeInTheDocument();
    expect(screen.getByText('Web chat')).toBeInTheDocument();
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

  it('Messenger + no Meta app -> the wizard\'s own page step offers a page, excluding an already-connected one', async () => {
    listMetaPages.mockResolvedValue({
      sessionId: 'sess-1',
      expiresAt: '2026-01-01T00:05:00Z',
      pages: PAGES.filter((p) => !p.connected),
    });
    render(<ChannelConnectWizard open onOpenChange={vi.fn()} />);
    await waitFor(() => expect(screen.getByRole('combobox', { name: 'Channel type' })).toBeInTheDocument());

    fireEvent.click(screen.getByRole('combobox', { name: 'Channel type' }));
    fireEvent.click(screen.getByText('Messenger'));
    await waitFor(() => expect(screen.getByRole('combobox', { name: 'Channel type' })).toHaveTextContent('Messenger'));

    fireEvent.click(screen.getByRole('button', { name: /Connect \(sandbox\)/ }));

    await waitFor(() => expect(screen.getByText('Choose a Page')).toBeInTheDocument());
    // pg-701 is already bound to a live channel elsewhere - filtered out by
    // the (mocked) real `listMetaPages` response, never offered.
    const trigger = screen.getByRole('combobox', { name: 'Facebook Page' });
    fireEvent.click(trigger);
    expect(screen.queryByText('Foundryx Events Co.')).not.toBeInTheDocument();
    expect(screen.getByText('Foundryx VIP Desk')).toBeInTheDocument();
  });

  it('every returned page already connected -> a proper empty state, no dead disabled Connect control (nit, security review round 1)', async () => {
    listMetaPages.mockResolvedValue({
      sessionId: 'sess-empty',
      expiresAt: '2026-01-01T00:05:00Z',
      pages: PAGES.map((p) => ({ ...p, connected: true })),
    });
    render(<ChannelConnectWizard open onOpenChange={vi.fn()} />);
    await waitFor(() => expect(screen.getByRole('combobox', { name: 'Channel type' })).toBeInTheDocument());

    fireEvent.click(screen.getByRole('combobox', { name: 'Channel type' }));
    fireEvent.click(screen.getByText('Messenger'));
    await waitFor(() => expect(screen.getByRole('combobox', { name: 'Channel type' })).toHaveTextContent('Messenger'));
    fireEvent.click(screen.getByRole('button', { name: /Connect \(sandbox\)/ }));

    await waitFor(() => expect(screen.getByTestId('wizard-no-available-pages')).toBeInTheDocument());
    expect(screen.queryByRole('combobox', { name: 'Facebook Page' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Connect' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeInTheDocument();
  });

  it('picking a page on the wizard\'s own page step connects the channel', async () => {
    listMetaPages.mockResolvedValue({
      sessionId: 'sess-2',
      expiresAt: '2026-01-01T00:05:00Z',
      pages: PAGES.filter((p) => !p.connected),
    });
    connectMetaChannel.mockResolvedValue(CHANNEL);
    const onConnected = vi.fn();
    render(<ChannelConnectWizard open onOpenChange={vi.fn()} onConnected={onConnected} />);
    await waitFor(() => expect(screen.getByRole('combobox', { name: 'Channel type' })).toBeInTheDocument());

    fireEvent.click(screen.getByRole('combobox', { name: 'Channel type' }));
    fireEvent.click(screen.getByText('Instagram'));
    await waitFor(() => expect(screen.getByRole('combobox', { name: 'Channel type' })).toHaveTextContent('Instagram'));
    fireEvent.click(screen.getByRole('button', { name: /Connect \(sandbox\)/ }));

    await waitFor(() => expect(screen.getByText('Choose a professional account')).toBeInTheDocument());
    fireEvent.click(screen.getByRole('combobox', { name: 'Instagram account' }));
    fireEvent.click(screen.getByText('foundryx.concierge'));
    await waitFor(() =>
      expect(screen.getByRole('combobox', { name: 'Instagram account' })).toHaveTextContent(
        'foundryx.concierge',
      ),
    );
    fireEvent.click(screen.getByRole('button', { name: 'Connect' }));

    await waitFor(() => expect(screen.getByText('Sandbox channel created')).toBeInTheDocument());
    expect(connectMetaChannel).toHaveBeenCalledWith(
      expect.objectContaining({ sessionId: 'sess-2', channelType: 'INSTAGRAM', pageId: 'pg-702' }),
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

describe('ChannelConnectWizard - plan 34 / A7b Web chat (AC-WEB-01/02)', () => {
  it('selecting Web chat skips the Meta popup entirely, asking only for a name + origins', async () => {
    render(<ChannelConnectWizard open onOpenChange={vi.fn()} />);
    await waitFor(() => expect(screen.getByRole('combobox', { name: 'Channel type' })).toBeInTheDocument());

    fireEvent.click(screen.getByRole('combobox', { name: 'Channel type' }));
    fireEvent.click(screen.getByText('Web chat'));
    await waitFor(() =>
      expect(screen.getByRole('combobox', { name: 'Channel type' })).toHaveTextContent('Web chat'),
    );

    // No Meta-app warning, no manual-connect link, no OAuth affordance at all.
    expect(screen.queryByText(/app not configured/)).not.toBeInTheDocument();
    expect(screen.queryByText('Set up manually (paste token)')).not.toBeInTheDocument();
    expect(screen.getByPlaceholderText('Website chat')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('https://crm.acme.com')).toBeInTheDocument();
  });

  it('"Connect" stays disabled until a name AND at least one valid origin are present', async () => {
    render(<ChannelConnectWizard open onOpenChange={vi.fn()} />);
    await waitFor(() => expect(screen.getByRole('combobox', { name: 'Channel type' })).toBeInTheDocument());
    fireEvent.click(screen.getByRole('combobox', { name: 'Channel type' }));
    fireEvent.click(screen.getByText('Web chat'));
    await waitFor(() =>
      expect(screen.getByRole('combobox', { name: 'Channel type' })).toHaveTextContent('Web chat'),
    );

    const connectButton = screen.getByRole('button', { name: 'Connect' });
    expect(connectButton).toBeDisabled();

    fireEvent.change(screen.getByPlaceholderText('Website chat'), { target: { value: 'Website chat' } });
    expect(connectButton).toBeDisabled();

    fireEvent.change(screen.getByPlaceholderText('https://crm.acme.com'), {
      target: { value: 'https://shop.acme.test' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Add' }));
    await waitFor(() => expect(connectButton).toBeEnabled());
  });

  it('an invalid origin surfaces the same field-level message the embed screen produces', async () => {
    render(<ChannelConnectWizard open onOpenChange={vi.fn()} />);
    await waitFor(() => expect(screen.getByRole('combobox', { name: 'Channel type' })).toBeInTheDocument());
    fireEvent.click(screen.getByRole('combobox', { name: 'Channel type' }));
    fireEvent.click(screen.getByText('Web chat'));
    await waitFor(() =>
      expect(screen.getByRole('combobox', { name: 'Channel type' })).toHaveTextContent('Web chat'),
    );

    fireEvent.change(screen.getByPlaceholderText('https://crm.acme.com'), {
      target: { value: 'not-a-url' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Add' }));
    expect(await screen.findByText(/is not a valid origin/i)).toBeInTheDocument();
  });

  it('connecting provisions the channel and reveals the widget secret exactly once', async () => {
    webchatConnect.mockResolvedValue({
      id: 'chn-web-9',
      name: 'Website chat',
      channelType: 'WEBCHAT',
      widgetSecret: 'whsec_only_shown_once',
    });
    const onConnected = vi.fn();
    render(<ChannelConnectWizard open onOpenChange={vi.fn()} onConnected={onConnected} />);
    await waitFor(() => expect(screen.getByRole('combobox', { name: 'Channel type' })).toBeInTheDocument());
    fireEvent.click(screen.getByRole('combobox', { name: 'Channel type' }));
    fireEvent.click(screen.getByText('Web chat'));
    await waitFor(() =>
      expect(screen.getByRole('combobox', { name: 'Channel type' })).toHaveTextContent('Web chat'),
    );

    fireEvent.change(screen.getByPlaceholderText('Website chat'), { target: { value: 'Website chat' } });
    fireEvent.change(screen.getByPlaceholderText('https://crm.acme.com'), {
      target: { value: 'https://shop.acme.test' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Add' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Connect' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: 'Connect' }));

    await waitFor(() => expect(screen.getByText('Channel connected')).toBeInTheDocument());
    expect(webchatConnect).toHaveBeenCalledWith({
      name: 'Website chat',
      workspaceId: 'wsp-1',
      allowedOrigins: ['https://shop.acme.test'],
    });
    expect(screen.getByDisplayValue('whsec_only_shown_once')).toBeInTheDocument();
  });
});
