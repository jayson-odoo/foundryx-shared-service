import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { useVisitorChat } from '@/hooks/use-visitor-chat';
import type { UseVisitorChatResult } from '@/hooks/use-visitor-chat';
import type { WebchatSessionResult } from '@/types/omnichannel';
import { WebchatPanel } from './webchat-panel';

vi.mock('@/hooks/use-visitor-chat', () => ({
  useVisitorChat: vi.fn(),
}));

const mockedUseVisitorChat = vi.mocked(useVisitorChat);

function baseSession(overrides: Partial<WebchatSessionResult> = {}): WebchatSessionResult {
  return {
    token: 'tok',
    expiresAt: '2026-10-01T00:00:00Z',
    visitorId: 'vis_1',
    workspaceId: 'ws_1',
    config: {
      appearance: {
        accentColor: '#FF5A00',
        position: 'right',
        headerTitle: 'Chat with us',
        agentDisplayName: 'Support',
      },
      greeting: 'Hi! How can we help you today?',
      offlineGreeting: "We're offline right now - leave a message and we'll reply.",
      preChat: { askName: false, askEmail: false, askPhone: false },
      agentDisplayName: 'Support',
      tenantName: null,
      brandTokens: {},
    },
    online: true,
    messages: [],
    ...overrides,
  };
}

function baseResult(overrides: Partial<UseVisitorChatResult> = {}): UseVisitorChatResult {
  return {
    phase: 'ready',
    session: baseSession(),
    messages: [],
    needsPreChat: false,
    sending: false,
    sendError: null,
    honeypot: '',
    setHoneypot: vi.fn(),
    send: vi.fn(),
    ...overrides,
  };
}

async function openPanel() {
  const user = userEvent.setup();
  await user.click(screen.getByTestId('webchat-launcher'));
}

describe('WebchatPanel with no loader session (BL-SS-183)', () => {
  it('renders NOTHING - no launcher, no copy, no vendor string - until a session arrives', () => {
    mockedUseVisitorChat.mockReturnValue(baseResult({ phase: 'waiting', session: null }));
    const { container } = render(<WebchatPanel widgetKey="wk_test" />);
    // This is exactly what a panel URL opened directly (no loader, so no
    // token and no session ever started server-side) shows a stranger.
    expect(container).toBeEmptyDOMElement();
    expect(screen.queryByTestId('webchat-launcher')).not.toBeInTheDocument();
  });
});

describe('WebchatPanel online/offline greeting (plan 34 / A7b S5, D-A7B-24/AC-WEB-52/53)', () => {
  it('shows the ONLINE greeting in the transcript when online is true', async () => {
    mockedUseVisitorChat.mockReturnValue(baseResult({ session: baseSession({ online: true }) }));
    render(<WebchatPanel widgetKey="wk_test" />);
    await openPanel();
    expect(screen.getByText('Hi! How can we help you today?')).toBeInTheDocument();
    expect(
      screen.queryByText("We're offline right now - leave a message and we'll reply."),
    ).not.toBeInTheDocument();
  });

  it('shows the OFFLINE greeting in the transcript when online is false', async () => {
    mockedUseVisitorChat.mockReturnValue(baseResult({ session: baseSession({ online: false }) }));
    render(<WebchatPanel widgetKey="wk_test" />);
    await openPanel();
    expect(
      screen.getByText("We're offline right now - leave a message and we'll reply."),
    ).toBeInTheDocument();
    expect(screen.queryByText('Hi! How can we help you today?')).not.toBeInTheDocument();
  });

  it('shows the OFFLINE greeting on the pre-chat step too, when a toggle is on', async () => {
    mockedUseVisitorChat.mockReturnValue(
      baseResult({
        session: baseSession({
          online: false,
          config: {
            ...baseSession().config,
            preChat: { askName: true, askEmail: false, askPhone: false },
          },
        }),
        needsPreChat: true,
      }),
    );
    render(<WebchatPanel widgetKey="wk_test" />);
    await openPanel();
    expect(
      screen.getByText("We're offline right now - leave a message and we'll reply."),
    ).toBeInTheDocument();
    // The message path is identical regardless of online/offline - the
    // pre-chat step's own send control is still present.
    expect(screen.getByTestId('webchat-prechat-send')).toBeInTheDocument();
  });

  it('falls back to the ONLINE greeting when offlineGreeting is empty', async () => {
    mockedUseVisitorChat.mockReturnValue(
      baseResult({
        session: baseSession({ online: false, config: { ...baseSession().config, offlineGreeting: '' } }),
      }),
    );
    render(<WebchatPanel widgetKey="wk_test" />);
    await openPanel();
    // An unset offlineGreeting is optional copy, not a required second
    // field - the panel never shows a visitor a blank system line.
    expect(screen.getByText('Hi! How can we help you today?')).toBeInTheDocument();
  });
});
