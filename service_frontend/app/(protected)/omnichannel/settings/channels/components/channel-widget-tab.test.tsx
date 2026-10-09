/**
 * Widget tab (plan 34 / A7b, AC-WEB-04/05/06) - appearance/greeting/pre-chat
 * fields on the shared record form, the reused install snippet, and the
 * reveal-once rotate-secret dialog.
 */
import { useForm } from 'react-hook-form';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { Form } from '@/components/ui/form';
import type { WebchatConfig } from '@/types/omnichannel';
import type { ChannelDetailValues } from './channel-schema';
import { ChannelWidgetTab } from './channel-widget-tab';

const rotateSecret = vi.fn();

vi.mock('@/hooks/use-webchat-config', () => ({
  useWebchatConfig: () => ({
    config: null,
    isLoading: false,
    error: null,
    refresh: vi.fn(),
    save: vi.fn(),
    rotateSecret: (...args: unknown[]) => rotateSecret(...args),
  }),
}));

vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({ can: () => true, ready: true, permissions: new Set<string>() }),
}));

const CONFIG: WebchatConfig = {
  widgetKey: 'wk_demo0000000000000000000001',
  allowedOrigins: ['https://shop.acme.test'],
  tokenEpoch: 0,
  appearance: { accentColor: '#FF5A00', position: 'right', headerTitle: 'Chat with us', agentDisplayName: 'Support' },
  greeting: 'Hi! How can we help?',
  offlineGreeting: "We're offline right now.",
  preChat: { askName: true, askEmail: true, askPhone: false },
  snippet: '<script src="https://app.example/omnichannel/widget/wk_demo.js" async></script>',
};

function Wrapper({ editing, webchatConfig }: { editing: boolean; webchatConfig: WebchatConfig | null }) {
  const form = useForm<ChannelDetailValues>({
    defaultValues: {
      name: 'Website chat',
      isActive: true,
      widgetAccentColor: webchatConfig?.appearance.accentColor,
      widgetPosition: webchatConfig?.appearance.position,
      widgetHeaderTitle: webchatConfig?.appearance.headerTitle,
      widgetAgentDisplayName: webchatConfig?.appearance.agentDisplayName,
      widgetGreeting: webchatConfig?.greeting,
      widgetOfflineGreeting: webchatConfig?.offlineGreeting,
      widgetAskName: webchatConfig?.preChat.askName,
      widgetAskEmail: webchatConfig?.preChat.askEmail,
      widgetAskPhone: webchatConfig?.preChat.askPhone,
    },
  });
  return (
    <Form {...form}>
      <ChannelWidgetTab form={form} editing={editing} channelId="chn-web-1" webchatConfig={webchatConfig} />
    </Form>
  );
}

describe('ChannelWidgetTab', () => {
  it('loading (no config yet): renders a skeleton, no field content', () => {
    render(<Wrapper editing={false} webchatConfig={null} />);
    expect(screen.queryByText('Hi! How can we help?')).not.toBeInTheDocument();
  });

  it('read mode: renders the populated fields as plain text, not inputs', () => {
    render(<Wrapper editing={false} webchatConfig={CONFIG} />);
    expect(screen.getByText('Hi! How can we help?')).toBeInTheDocument();
    expect(screen.getByText('Chat with us')).toBeInTheDocument();
    expect(screen.getByText('Right')).toBeInTheDocument();
    expect(screen.queryByRole('textbox', { name: /header title/i })).not.toBeInTheDocument();
  });

  it('edit mode: renders editable inputs bound to the shared record form', () => {
    render(<Wrapper editing webchatConfig={CONFIG} />);
    expect(screen.getByDisplayValue('Chat with us')).toBeInTheDocument();
    expect(screen.getByDisplayValue('Support')).toBeInTheDocument();
  });

  it('every dropdown is a SearchSelect (position picker)', () => {
    render(<Wrapper editing webchatConfig={CONFIG} />);
    expect(screen.getByRole('combobox', { name: 'Launcher position' })).toBeInTheDocument();
  });

  it('renders the install snippet through the reused SnippetCard/CopyField, verbatim from the backend', () => {
    render(<Wrapper editing={false} webchatConfig={CONFIG} />);
    expect(screen.getByText(CONFIG.snippet)).toBeInTheDocument();
  });

  it('rotate-secret action reveals the new secret once, in a dialog, never on load', async () => {
    rotateSecret.mockResolvedValue('whsec_freshly_rotated');
    const user = userEvent.setup();
    render(<Wrapper editing={false} webchatConfig={CONFIG} />);

    // Never shown before the action runs.
    expect(screen.queryByText('whsec_freshly_rotated')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Actions' }));
    await user.click(await screen.findByRole('menuitem', { name: 'Rotate widget secret' }));

    await waitFor(() => expect(screen.getByDisplayValue('whsec_freshly_rotated')).toBeInTheDocument());
    expect(screen.getByText("Copy this secret now - it won't be shown again.")).toBeInTheDocument();
  });
});
