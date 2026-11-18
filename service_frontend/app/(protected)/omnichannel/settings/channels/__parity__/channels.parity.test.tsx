/**
 * Switch-off parity for the channels pages (Foundryx UIUX, slice W2-CHAN).
 * Recorded on the code BEFORE the slice changed anything, so a later change
 * that alters what a user sees or what reaches the backend with the switch
 * off fails here. A change that needs one of these snapshots updated is wrong
 * by definition: fix the code, never the snapshot.
 *
 * Covers: the channels list, the channel record (Configuration tab, Test
 * connection, Sync, Save), the Replace token dialog, the Webhooks tab (Add
 * endpoint with its one-time secret, Rotate secret), the Widget tab's rotate,
 * the connect wizard (intro, manual connect, web chat, Messenger page pick,
 * the WhatsApp sandbox popup, a failure), the Templates tab, the template
 * builder (new and existing, Save draft, Submit), the bubble preview and the
 * WhatsApp sign-in callback page.
 */
import type { ReactElement } from 'react';
import { fireEvent, render as rtlRender, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { SettingsProvider } from '@/providers/settings-provider';
import {
  answers,
  calls,
  channel,
  parityHtml,
  resetCalls,
  settle,
  templateDetail,
} from './channel-test-kit';

const h = vi.hoisted(() => ({
  params: { id: 'chn-1' } as Record<string, string>,
  search: new URLSearchParams(),
  pathname: '/omnichannel/settings/channels',
}));

vi.mock('@/lib/toast', async () => (await import('./channel-test-kit')).toastMock);
vi.mock('@/services/channel-service', async () => (await import('./channel-test-kit')).channelServiceMock);
vi.mock('@/services/webchat-service', async () => (await import('./channel-test-kit')).webchatServiceMock);
vi.mock('@/services/onboarding-service', async () => (await import('./channel-test-kit')).onboardingServiceMock);
vi.mock('@/services/whatsapp-webhook-service', async () => (await import('./channel-test-kit')).webhookServiceMock);
vi.mock('@/services/whatsapp-template-service', async () => (await import('./channel-test-kit')).templateServiceMock);
vi.mock('@/services/workspace-service', async () => (await import('./channel-test-kit')).workspaceServiceMock);
vi.mock('@/services/pending-actions-service', async () => (await import('./channel-test-kit')).pendingActionsServiceMock);
vi.mock('@/services/preferences-service', async () => (await import('./channel-test-kit')).preferencesServiceMock);

vi.mock('next/navigation', async () => {
  const kit = await import('./channel-test-kit');
  const router = {
    push: (...args: unknown[]) => kit.calls.push(['router.push', ...args]),
    replace: (...args: unknown[]) => kit.calls.push(['router.replace', ...args]),
    prefetch: () => undefined,
    back: () => undefined,
    refresh: () => undefined,
  };
  return {
    useRouter: () => router,
    usePathname: () => h.pathname,
    useSearchParams: () => h.search,
    useParams: () => h.params,
  };
});

vi.mock('next-auth/react', () => ({
  useSession: () => ({
    data: { user: { name: 'Kay Tan', timezone: 'Asia/Kuala_Lumpur', permissions: [] } },
    status: 'authenticated',
  }),
  getSession: () => Promise.resolve(null),
  signOut: () => undefined,
}));

vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({ can: () => true, ready: true, permissions: new Set<string>() }),
}));

vi.mock('@/components/common/require-permission', () => ({
  RequirePermission: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock('@/lib/impersonation-store', () => ({ useImpersonationSession: () => null }));
vi.mock('@/services/terminology-service', () => ({
  terminologyService: { getTerminology: () => Promise.resolve({}) },
}));
vi.mock('@/providers/import-activity-provider', () => ({
  useImportActivity: () => ({ openImport: () => undefined }),
}));

// Imported after the mocks.
import ChannelsPage from '../page';
import { ChannelFormView } from '../components/channel-form-view';
import { ReplaceTokenDialog } from '../components/replace-token-dialog';
import { WebhooksPanel } from '../components/channel-webhooks-tab';
import { ChannelTemplatesTab } from '../components/channel-templates-tab';
import { TemplateBuilderView } from '../[id]/templates/components/template-builder-view';
import { WaBubblePreview } from '../[id]/templates/components/wa-bubble-preview';
import { ChannelConnectWizard } from '@/components/platform/channel-connect-wizard';
import WaCallbackPage from '@/app/wa-callback/page';

function render(ui: ReactElement) {
  return rtlRender(<SettingsProvider>{ui}</SettingsProvider>);
}

beforeEach(() => {
  resetCalls();
  answers.channel = channel();
  answers.testOk = true;
  answers.manualFails = false;
  answers.templateDetail = templateDetail();
  h.params = { id: 'chn-1' };
  h.search = new URLSearchParams();
  window.localStorage.clear();
});

describe('channels list (switch off)', () => {
  it('renders the list as today', async () => {
    const { container } = render(<ChannelsPage />);
    await screen.findByText('Support line');
    await settle();
    expect(parityHtml(container)).toMatchSnapshot();
  });
});

describe('channel record (switch off)', () => {
  it('renders the Configuration tab and runs Test connection and Sync as today', async () => {
    const { container } = render(<ChannelFormView channelId="chn-1" initialEditing={false} />);
    await screen.findByText('Maju Trading Sdn Bhd');
    await settle();
    expect(parityHtml(container)).toMatchSnapshot('read');

    fireEvent.click(screen.getByRole('button', { name: /Test connection/ }));
    await settle();
    answers.testOk = false;
    fireEvent.click(screen.getByRole('button', { name: /Test connection/ }));
    await settle();
    fireEvent.click(screen.getByRole('button', { name: /^Sync$/ }));
    await settle();
    expect(calls.filter((c) => c[0] !== 'channel.get')).toMatchSnapshot('calls');
  });

  it('saves the edited name and profile with the same bodies as today', async () => {
    render(<ChannelFormView channelId="chn-1" initialEditing />);
    await screen.findByPlaceholderText('Channel name');
    await settle();
    fireEvent.change(screen.getByPlaceholderText('Channel name'), { target: { value: 'Maju Sales Main' } });
    await settle();
    fireEvent.click(screen.getByRole('button', { name: /^Save/ }));
    await settle(100);
    expect(calls.filter((c) => c[0] !== 'channel.get')).toMatchSnapshot('calls');
  });

  it('shows the error status reason as today', async () => {
    answers.channel = channel({ id: 'chn-2', name: 'Support line', status: 'ERROR' });
    const { container } = render(<ChannelFormView channelId="chn-2" initialEditing={false} />);
    await screen.findByText('Access token expired or revoked');
    await settle();
    expect(parityHtml(container)).toMatchSnapshot();
  });
});

describe('widget tab (switch off)', () => {
  it('rotates the widget secret and shows it once, as today', async () => {
    answers.channel = channel({ id: 'chn-web', channelType: 'WEBCHAT', name: 'Maju site', displayPhoneNumber: null });
    render(<ChannelFormView channelId="chn-web" initialEditing={false} />);
    await screen.findByText('Maju site', { selector: 'h1, span, div' }).catch(() => undefined);
    await settle();
    fireEvent.mouseDown(screen.getByRole('tab', { name: /Widget/ }));
    fireEvent.click(screen.getByRole('tab', { name: /Widget/ }));
    await screen.findByText('Widget secret');
    const menu = screen.getAllByRole('button', { name: /actions/i }).at(-1) as HTMLElement;
    fireEvent.pointerDown(menu, { button: 0, pointerType: 'mouse' });
    fireEvent.click(await screen.findByRole('menuitem', { name: /Rotate widget secret/ }));
    await screen.findByText('Widget secret rotated');
    expect(parityHtml(screen.getByRole('dialog'))).toMatchSnapshot('rotated');
    expect(calls.filter((c) => c[0] !== 'channel.get')).toMatchSnapshot('calls');
  });
});

describe('replace token dialog (switch off)', () => {
  it('renders and saves the same request as today', async () => {
    const onReplaced = vi.fn();
    render(<ReplaceTokenDialog channel={channel()} open onOpenChange={() => undefined} onReplaced={onReplaced} />);
    const dialog = await screen.findByRole('dialog');
    expect(parityHtml(dialog)).toMatchSnapshot('html');
    fireEvent.change(screen.getByLabelText('Permanent access token (System User)'), {
      target: { value: '  EAAGtoken123  ' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save token' }));
    await settle();
    expect(onReplaced).toHaveBeenCalled();
    expect(calls).toMatchSnapshot('calls');
  });
});

describe('webhooks tab (switch off)', () => {
  it('renders, adds an endpoint showing its secret once, and rotates as today', async () => {
    const { container } = render(<WebhooksPanel scopeId="chn-1" channelId="chn-1" />);
    await screen.findByText('CRM sync');
    await settle();
    expect(parityHtml(container)).toMatchSnapshot('list');

    fireEvent.click(screen.getByRole('button', { name: /Add endpoint/ }));
    const dialog = await screen.findByRole('dialog');
    fireEvent.change(within(dialog).getByLabelText('Name'), { target: { value: 'ERP hook' } });
    fireEvent.change(within(dialog).getByLabelText('Endpoint URL'), {
      target: { value: 'https://erp.maju.example/hook' },
    });
    fireEvent.click(within(dialog).getByRole('combobox'));
    fireEvent.click(await screen.findByRole('option', { name: /Inbound messages/ }));
    await settle();
    fireEvent.click(within(dialog).getByRole('button', { name: /Add endpoint/, hidden: true }));
    await screen.findByText('Endpoint created');
    expect(parityHtml(screen.getByRole('dialog'))).toMatchSnapshot('secret');
    fireEvent.click(screen.getByRole('button', { name: 'Done' }));
    await settle();

    const rows = screen.getAllByRole('button', { name: /actions/i });
    fireEvent.pointerDown(rows[0], { button: 0, pointerType: 'mouse' });
    fireEvent.click(await screen.findByRole('menuitem', { name: /Rotate secret/ }));
    await screen.findByText('Signing secret rotated');
    expect(parityHtml(screen.getByRole('dialog'))).toMatchSnapshot('rotated');
    expect(calls.filter((c) => c[0] !== 'webhook.list')).toMatchSnapshot('calls');
  });
});

describe('connect wizard (switch off)', () => {
  it('renders the intro as today', async () => {
    render(<ChannelConnectWizard open onOpenChange={() => undefined} />);
    await screen.findByText('Connect a channel');
    await settle();
    expect(parityHtml(screen.getByRole('dialog'))).toMatchSnapshot();
  });

  it('connects a WhatsApp sandbox number as today', async () => {
    const onConnected = vi.fn();
    render(<ChannelConnectWizard open onOpenChange={() => undefined} onConnected={onConnected} />);
    await screen.findByText('Connect a channel');
    await settle();
    fireEvent.click(screen.getByRole('button', { name: /Connect \(sandbox\)/ }));
    fireEvent.click(await screen.findByTestId('mock-meta-authorize'));
    await screen.findByText('Sandbox channel created');
    expect(parityHtml(screen.getByRole('dialog'))).toMatchSnapshot('connected');
    expect(calls).toMatchSnapshot('calls');
  });

  it('connects manually as today, and shows a failure as today', async () => {
    render(<ChannelConnectWizard open onOpenChange={() => undefined} />);
    await screen.findByText('Connect a channel');
    await settle();
    fireEvent.click(screen.getByRole('button', { name: /Set up manually/ }));
    await screen.findByText('Set up manually');
    expect(parityHtml(screen.getByRole('dialog'))).toMatchSnapshot('manual');
    answers.manualFails = true;
    fireEvent.change(screen.getByLabelText('Permanent access token (System User)'), {
      target: { value: ' EAAGmanual ' },
    });
    fireEvent.change(screen.getByPlaceholderText('e.g. 123456789012345'), { target: { value: ' 1098765 ' } });
    fireEvent.change(screen.getByPlaceholderText('WhatsApp Business Account ID'), { target: { value: 'waba-9' } });
    fireEvent.click(screen.getByRole('button', { name: 'Connect' }));
    await screen.findByText('Connection failed');
    expect(parityHtml(screen.getByRole('dialog'))).toMatchSnapshot('failed');
    expect(calls).toMatchSnapshot('calls');
  });

  it('connects a web chat channel and shows its secret as today', async () => {
    render(<ChannelConnectWizard open onOpenChange={() => undefined} />);
    await screen.findByText('Connect a channel');
    await settle();
    fireEvent.click(screen.getByRole('combobox', { name: 'Channel type' }));
    fireEvent.click(await screen.findByRole('option', { name: 'Web chat' }));
    await settle();
    fireEvent.change(screen.getByPlaceholderText('Website chat'), { target: { value: ' Maju site ' } });
    const origin = screen.getByRole('textbox', { name: /origin/i });
    fireEvent.change(origin, { target: { value: 'https://maju.example' } });
    fireEvent.keyDown(origin, { key: 'Enter' });
    await settle();
    fireEvent.click(screen.getByRole('button', { name: /^Connect$/ }));
    await screen.findByText('Channel connected');
    expect(parityHtml(screen.getByRole('dialog'))).toMatchSnapshot('connected');
    expect(calls).toMatchSnapshot('calls');
  });

  it('connects a Messenger page as today', async () => {
    render(<ChannelConnectWizard open onOpenChange={() => undefined} />);
    await screen.findByText('Connect a channel');
    await settle();
    fireEvent.click(screen.getByRole('combobox', { name: 'Channel type' }));
    fireEvent.click(await screen.findByRole('option', { name: 'Messenger' }));
    await settle();
    fireEvent.click(screen.getByRole('button', { name: /Connect \(sandbox\)/ }));
    await screen.findByText('Choose a Page');
    expect(parityHtml(screen.getByRole('dialog'))).toMatchSnapshot('pick');
    fireEvent.click(screen.getByRole('combobox', { name: 'Facebook Page' }));
    fireEvent.click(await screen.findByRole('option', { name: 'Maju Concierge' }));
    await settle();
    fireEvent.click(screen.getByRole('button', { name: 'Connect', hidden: true }));
    await screen.findByText('Sandbox channel created');
    const masked = calls.map((c) =>
      c[0] === 'onboarding.listMetaPages'
        ? [c[0], { ...(c[1] as object), code: String((c[1] as { code: string }).code).replace(/\d+/, 'N') }]
        : c,
    );
    expect(masked).toMatchSnapshot('calls');
  });
});

describe('templates (switch off)', () => {
  it('renders the Templates tab and syncs as today', async () => {
    const { container } = render(<ChannelTemplatesTab channelId="chn-1" />);
    await screen.findByText('promo_nov_2026');
    await settle();
    expect(parityHtml(container)).toMatchSnapshot('list');
    fireEvent.click(screen.getByRole('button', { name: /^Sync$/ }));
    await settle();
    expect(calls.filter((c) => c[0] !== 'template.listManage')).toMatchSnapshot('calls');
  });

  it('builds a new template and saves the draft as today', async () => {
    const { container } = render(<TemplateBuilderView channelId="chn-1" />);
    await screen.findByText('New template');
    expect(parityHtml(container)).toMatchSnapshot('empty');
    fireEvent.change(screen.getByPlaceholderText(/order_update|lowercase|name/i), {
      target: { value: 'order_ready' },
    });
    const body = container.querySelector('textarea') as HTMLTextAreaElement;
    fireEvent.change(body, { target: { value: 'Hi {{1}}, your order is ready.' } });
    await settle();
    expect(parityHtml(container)).toMatchSnapshot('filled');
    fireEvent.click(screen.getByRole('button', { name: /Save draft/ }));
    await settle();
    fireEvent.change(screen.getByPlaceholderText('Sample for {{1}}'), { target: { value: 'Aisyah' } });
    fireEvent.click(screen.getByRole('button', { name: /Save draft/ }));
    await settle();
    expect(calls).toMatchSnapshot('calls');
  });

  it('opens an existing draft, submits it and guards leaving as today', async () => {
    const { container } = render(<TemplateBuilderView channelId="chn-1" templateId="tpl-1" />);
    await screen.findByRole('button', { name: /Submit template/ });
    await settle();
    expect(parityHtml(container)).toMatchSnapshot('draft');
    const body = container.querySelector('textarea') as HTMLTextAreaElement;
    fireEvent.change(body, { target: { value: 'Hi {{1}}, your order has shipped.' } });
    fireEvent.click(screen.getByRole('button', { name: /Back to channel/ }));
    await screen.findByText('Discard changes?');
    expect(parityHtml(screen.getByRole('alertdialog'))).toMatchSnapshot('guard');
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    await settle();
    fireEvent.click(screen.getByRole('button', { name: /Submit template/ }));
    await settle(100);
    expect(calls).toMatchSnapshot('calls');
  });

  it('renders the bubble preview as today', () => {
    const { container } = rtlRender(<WaBubblePreview doc={templateDetail().doc} />);
    expect(parityHtml(container)).toMatchSnapshot();
  });
});

describe('WhatsApp sign-in callback (switch off)', () => {
  it('posts the code to the opener and says done, as today', async () => {
    const postMessage = vi.fn();
    const close = vi.spyOn(window, 'close').mockImplementation(() => undefined);
    Object.defineProperty(window, 'opener', { value: { postMessage }, configurable: true });
    window.history.replaceState(null, '', '/wa-callback?code=abc123');
    const { container } = rtlRender(<WaCallbackPage />);
    await waitFor(() => expect(postMessage).toHaveBeenCalled());
    expect(postMessage.mock.calls).toMatchSnapshot('message');
    expect(parityHtml(container)).toMatchSnapshot('html');
    Object.defineProperty(window, 'opener', { value: null, configurable: true });
    close.mockRestore();
    window.history.replaceState(null, '', '/');
  });

  it('says cancelled without an opener, as today', async () => {
    Object.defineProperty(window, 'opener', { value: null, configurable: true });
    window.history.replaceState(null, '', '/wa-callback?error=access_denied');
    const { container } = rtlRender(<WaCallbackPage />);
    await screen.findByText('access_denied');
    expect(parityHtml(container)).toMatchSnapshot();
    window.history.replaceState(null, '', '/');
  });
});
