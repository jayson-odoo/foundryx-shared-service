/**
 * The channels pages with the Foundryx UIUX switch on (slice W2-CHAN).
 *
 * The core guarantee: every request that connects, reconnects, disconnects,
 * tests, rotates a secret or creates, updates or submits a template is the
 * same with the switch on as with it off, for the same input. Each scenario
 * below runs once per look through that look's own screen and compares the
 * writes that reached the services. Then the new look's own behaviour:
 * service cards with Connect, the card view, test results beside the action,
 * show-once secrets, the rotate confirm, the template builder's red action and
 * the bubble preview on tokens.
 */
import type { ReactElement, ReactNode } from 'react';
import { act, fireEvent, render as rtlRender, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SettingsProvider } from '@/providers/settings-provider';
import { FxProvider } from '@/providers/fx-provider';
import { FX_DEFAULT_THEME } from '@/lib/fx/cookies';
import { resetPageActionsForTests } from '@/components/fx/actions/page-actions-context';
import { answers, calls, channel, resetCalls, settle, templateDetail, writeCalls } from './channel-test-kit';
import { resetChannelTestResults } from '../components/channel-test-results';

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

vi.mock('next-auth/react', async () => {
  const { createContext } = await import('react');
  const session = {
    data: { user: { name: 'Kay Tan', timezone: 'Asia/Kuala_Lumpur', permissions: [] } },
    status: 'authenticated',
  };
  return {
    SessionContext: createContext(session),
    useSession: () => session,
    getSession: () => Promise.resolve(null),
    signOut: () => undefined,
  };
});

vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({ can: () => true, ready: true, permissions: new Set<string>() }),
}));
vi.mock('@/components/common/require-permission', () => ({
  RequirePermission: ({ children }: { children: ReactNode }) => <>{children}</>,
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
import { fxConnectNote } from '@/components/platform/channel-connect-wizard/fx-channel-connect-wizard';
import WaCallbackPage from '@/app/wa-callback/page';

type Look = 'off' | 'on';

function render(ui: ReactElement, look: Look) {
  const inner = <SettingsProvider>{ui}</SettingsProvider>;
  return rtlRender(
    look === 'on' ? (
      <FxProvider initial initialTheme={FX_DEFAULT_THEME}>
        {inner}
      </FxProvider>
    ) : (
      inner
    ),
  );
}

function reset() {
  resetCalls();
  resetChannelTestResults();
  resetPageActionsForTests();
  answers.channel = channel();
  answers.testOk = true;
  answers.manualFails = false;
  answers.templateDetail = templateDetail();
  h.params = { id: 'chn-1' };
  h.search = new URLSearchParams();
  window.localStorage.clear();
  // The confirm's press-and-hold is the foundation's (tested there); here the
  // single-click form keeps the scenarios short.
  window.localStorage.setItem('fx_settings', JSON.stringify({ hold: false }));
}

beforeEach(reset);
afterEach(() => {
  document.documentElement.removeAttribute('data-fx');
});

/** Runs `drive` once per look and returns the writes each look made. */
async function bothLooks(drive: (look: Look) => Promise<void>): Promise<{ off: unknown[][]; on: unknown[][] }> {
  const out: Record<Look, unknown[][]> = { off: [], on: [] };
  for (const look of ['off', 'on'] as const) {
    reset();
    await drive(look);
    out[look] = writeCalls();
    document.body.innerHTML = '';
  }
  return out;
}

const button = (name: RegExp | string) => screen.getByRole('button', { name, hidden: true });

/** A button by its visible words (the header's icon actions carry the same
 *  name as their tooltip). */
function tabButton(root: HTMLElement, text: string): HTMLElement {
  const found = within(root)
    .getAllByRole('button', { hidden: true })
    .find((b) => b.textContent?.trim() === text);
  if (!found) throw new Error(`No button reading "${text}"`);
  return found;
}

describe('the same writes with the switch on (Meta-facing requests)', () => {
  it('Test connection and Sync on the channel record', async () => {
    const { off, on } = await bothLooks(async (look) => {
      const view = render(<ChannelFormView channelId="chn-1" initialEditing={false} />, look);
      await screen.findByText('Maju Trading Sdn Bhd');
      await settle();
      fireEvent.click(tabButton(view.container, 'Test connection'));
      await settle();
      answers.testOk = false;
      fireEvent.click(tabButton(view.container, 'Test connection'));
      await settle();
      fireEvent.click(tabButton(view.container, look === 'on' ? 'Sync from Meta' : 'Sync'));
      await settle();
      view.unmount();
    });
    expect(off.length).toBe(3);
    expect(on).toEqual(off);
  });

  it('Save on the channel record (name and Business Profile)', async () => {
    const { off, on } = await bothLooks(async (look) => {
      const view = render(<ChannelFormView channelId="chn-1" initialEditing />, look);
      await screen.findByPlaceholderText('Channel name');
      await settle();
      fireEvent.change(screen.getByPlaceholderText('Channel name'), { target: { value: 'Maju Sales Main' } });
      await settle();
      const save = screen.getAllByRole('button', { name: /^Save/, hidden: true })[0];
      fireEvent.click(save);
      await settle(150);
      view.unmount();
    });
    expect(off.map((c) => c[0])).toEqual(['channel.update', 'channel.saveProfile']);
    expect(on).toEqual(off);
  });

  it('Replace token (Reconnect)', async () => {
    const { off, on } = await bothLooks(async (look) => {
      const view = render(
        <ReplaceTokenDialog channel={channel()} open onOpenChange={() => undefined} onReplaced={() => undefined} />,
        look,
      );
      await screen.findByRole('dialog');
      fireEvent.change(screen.getByLabelText('Permanent access token (System User)'), {
        target: { value: '  EAAGtoken123  ' },
      });
      fireEvent.click(button(look === 'on' ? 'Replace token' : 'Save token'));
      await settle();
      view.unmount();
    });
    expect(off).toEqual([['channel.replaceChannelToken', 'chn-1', 'EAAGtoken123']]);
    expect(on).toEqual(off);
  });

  it('Add endpoint and Rotate secret on the Webhooks tab', async () => {
    const { off, on } = await bothLooks(async (look) => {
      const view = render(<WebhooksPanel scopeId="chn-1" channelId="chn-1" />, look);
      await screen.findAllByText('CRM sync');
      await settle();
      fireEvent.click(screen.getAllByRole('button', { name: /Add endpoint/, hidden: true })[0]);
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
      fireEvent.click(button('Done'));
      await settle();
      const menus = screen.getAllByRole('button', { name: /actions/i, hidden: true });
      fireEvent.pointerDown(menus[0], { button: 0, pointerType: 'mouse' });
      fireEvent.click(await screen.findByRole('menuitem', { name: /Rotate secret/ }));
      if (look === 'on') {
        await screen.findByText('Rotate the signing secret for CRM sync?');
        expect(writeCalls().some((c) => c[0] === 'webhook.rotate')).toBe(false);
        fireEvent.click(button('Rotate secret'));
      }
      await screen.findByText(look === 'on' ? 'New signing secret for CRM sync' : 'Signing secret rotated');
      view.unmount();
    });
    expect(off.map((c) => c[0])).toEqual(['webhook.create', 'webhook.rotate']);
    expect(on).toEqual(off);
  });

  it('Rotate widget secret on the Widget tab', async () => {
    const { off, on } = await bothLooks(async (look) => {
      answers.channel = channel({ id: 'chn-web', channelType: 'WEBCHAT', name: 'Maju site', displayPhoneNumber: null });
      const view = render(<ChannelFormView channelId="chn-web" initialEditing={false} />, look);
      await settle(100);
      const tab = screen.getByRole('tab', { name: /Widget/, hidden: true });
      fireEvent.mouseDown(tab);
      fireEvent.click(tab);
      await screen.findByText('Widget secret');
      const menu = screen.getAllByRole('button', { name: /actions/i, hidden: true }).at(-1) as HTMLElement;
      fireEvent.pointerDown(menu, { button: 0, pointerType: 'mouse' });
      fireEvent.click(await screen.findByRole('menuitem', { name: /Rotate widget secret/ }));
      if (look === 'on') {
        await screen.findByText('Rotate the widget secret?');
        fireEvent.click(button('Rotate secret'));
      }
      await screen.findByText(look === 'on' ? 'New widget secret' : 'Widget secret rotated');
      view.unmount();
    });
    expect(off).toEqual([['webchat.rotateSecret', 'chn-web']]);
    expect(on).toEqual(off);
  });

  it('Connect: the WhatsApp sandbox number', async () => {
    const { off, on } = await bothLooks(async (look) => {
      const view = render(<ChannelConnectWizard open onOpenChange={() => undefined} />, look);
      await screen.findByText('Connect a channel');
      await settle();
      fireEvent.click(button(look === 'on' ? /Create sandbox channel/ : /Connect \(sandbox\)/));
      fireEvent.click(await screen.findByTestId('mock-meta-authorize'));
      await screen.findByText('Sandbox channel created');
      view.unmount();
    });
    expect(off.map((c) => c[0])).toEqual(['onboarding.completeOnboarding']);
    expect(on).toEqual(off);
  });

  it('Connect: a pasted token, failing, then retried', async () => {
    const { off, on } = await bothLooks(async (look) => {
      answers.manualFails = true;
      const view = render(<ChannelConnectWizard open onOpenChange={() => undefined} />, look);
      await screen.findByText('Connect a channel');
      await settle();
      fireEvent.click(button(look === 'on' ? /Connect with a token instead/ : /Set up manually/));
      await settle();
      fireEvent.change(screen.getByLabelText('Permanent access token (System User)'), {
        target: { value: ' EAAGmanual ' },
      });
      if (look === 'on') {
        fireEvent.change(screen.getByLabelText('Phone Number ID'), { target: { value: ' 1098765 ' } });
        fireEvent.change(screen.getByLabelText('WABA ID (optional)'), { target: { value: 'waba-9' } });
        fireEvent.click(button('Connect WhatsApp'));
        await screen.findByText('Meta rejected the token.');
      } else {
        fireEvent.change(screen.getByPlaceholderText('e.g. 123456789012345'), { target: { value: ' 1098765 ' } });
        fireEvent.change(screen.getByPlaceholderText('WhatsApp Business Account ID'), { target: { value: 'waba-9' } });
        fireEvent.click(button('Connect'));
        await screen.findByText('Connection failed');
      }
      view.unmount();
    });
    expect(off).toEqual([
      [
        'onboarding.manualConnect',
        { accessToken: 'EAAGmanual', phoneNumber: undefined, phoneNumberId: '1098765', wabaId: 'waba-9', workspaceId: 'wsp-1' },
      ],
    ]);
    expect(on).toEqual(off);
  });

  it('Connect: a web chat channel', async () => {
    const { off, on } = await bothLooks(async (look) => {
      const view = render(<ChannelConnectWizard open onOpenChange={() => undefined} />, look);
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
      fireEvent.click(button(look === 'on' ? 'Connect web chat' : /^Connect$/));
      await screen.findByText(look === 'on' ? 'Web chat connected' : 'Channel connected');
      view.unmount();
    });
    expect(off.map((c) => c[0])).toEqual(['webchat.connect']);
    expect(on).toEqual(off);
  });

  it('Connect: a Messenger page', async () => {
    const strip = (rows: unknown[][]) =>
      rows.map((c) =>
        c[0] === 'onboarding.listMetaPages' ? [c[0], { ...(c[1] as object), code: 'simulated' }] : c,
      );
    const { off, on } = await bothLooks(async (look) => {
      const view = render(<ChannelConnectWizard open onOpenChange={() => undefined} />, look);
      await screen.findByText('Connect a channel');
      await settle();
      fireEvent.click(screen.getByRole('combobox', { name: 'Channel type' }));
      fireEvent.click(await screen.findByRole('option', { name: 'Messenger' }));
      await settle();
      fireEvent.click(button(look === 'on' ? /Create sandbox channel/ : /Connect \(sandbox\)/));
      await screen.findByText(look === 'on' ? 'Choose the Facebook Page' : 'Choose a Page');
      fireEvent.click(screen.getByRole('combobox', { name: 'Facebook Page' }));
      fireEvent.click(await screen.findByRole('option', { name: 'Maju Concierge' }));
      await settle();
      fireEvent.click(button(look === 'on' ? 'Connect Maju Concierge' : 'Connect'));
      await screen.findByText(look === 'on' ? 'Sandbox channel created' : 'Sandbox channel created');
      view.unmount();
    });
    expect(strip(off).map((c) => c[0])).toEqual(['onboarding.listMetaPages', 'onboarding.connectMetaChannel']);
    expect(strip(on)).toEqual(strip(off));
  });

  it('Templates: Sync', async () => {
    const { off, on } = await bothLooks(async (look) => {
      const view = render(<ChannelTemplatesTab channelId="chn-1" />, look);
      await screen.findAllByText('promo_nov_2026');
      await settle();
      fireEvent.click(button(look === 'on' ? /Sync from Meta/ : /^Sync$/));
      await settle();
      view.unmount();
    });
    expect(off).toEqual([['template.sync', 'chn-1']]);
    expect(on).toEqual(off);
  });

  it('Template builder: a new draft, refused once, then saved, then submitted', async () => {
    const { off, on } = await bothLooks(async (look) => {
      const view = render(<TemplateBuilderView channelId="chn-1" />, look);
      await screen.findAllByText('New template');
      fireEvent.change(screen.getByPlaceholderText('order_update'), { target: { value: 'order_ready' } });
      const body = view.container.querySelector('textarea') as HTMLTextAreaElement;
      fireEvent.change(body, { target: { value: 'Hi {{1}}, your order is ready.' } });
      await settle();
      const save = () =>
        fireEvent.click(screen.getAllByRole('button', { name: /Save draft/, hidden: true })[0]);
      save();
      await settle();
      fireEvent.change(screen.getByPlaceholderText('Sample for {{1}}'), { target: { value: 'Aisyah' } });
      await settle();
      save();
      await settle();
      fireEvent.click(screen.getAllByRole('button', { name: /^Submit/, hidden: true })[0]);
      await settle(100);
      view.unmount();
    });
    expect(off.map((c) => c[0])).toEqual(['template.saveDraft', 'template.edit', 'template.submit']);
    expect(on).toEqual(off);
  });

  it('Template builder: an existing draft edited and submitted', async () => {
    const { off, on } = await bothLooks(async (look) => {
      const view = render(<TemplateBuilderView channelId="chn-1" templateId="tpl-1" />, look);
      await waitFor(() =>
        expect(screen.getAllByRole('button', { name: /^Submit/, hidden: true }).length).toBeGreaterThan(0),
      );
      await settle();
      const body = view.container.querySelector('textarea') as HTMLTextAreaElement;
      fireEvent.change(body, { target: { value: 'Hi {{1}}, your order has shipped.' } });
      await settle();
      fireEvent.click(screen.getAllByRole('button', { name: /^Submit/, hidden: true })[0]);
      await settle(100);
      view.unmount();
    });
    expect(off.map((c) => c[0])).toEqual(['template.edit', 'template.submit']);
    expect(on).toEqual(off);
  });
});

describe('the new look', () => {
  it('channels page: a card per service with its own Connect, opening the wizard on that type', async () => {
    render(<ChannelsPage />, 'on');
    await screen.findAllByText('Support line');
    await settle();
    const services = screen.getByRole('region', { name: 'Connect a service' });
    expect(within(services).getByText('2 connected')).toBeInTheDocument();
    expect(within(services).getByText('1 connected')).toBeInTheDocument();
    expect(within(services).getAllByText('Not connected')).toHaveLength(2);
    // Connected channels show as cards with their account and state.
    expect(screen.getByText('Maju Sales · +60 3-7890 1200')).toBeInTheDocument();
    expect(screen.getByText('Needs attention')).toBeInTheDocument();
    expect(
      screen.getByText('Access expired or was revoked. Reconnect to keep receiving messages.'),
    ).toBeInTheDocument();
    // No list-level Connect: it lives on the service cards.
    expect(screen.queryByRole('button', { name: 'Connect channel' })).not.toBeInTheDocument();

    fireEvent.click(within(services).getByRole('button', { name: 'Connect Messenger' }));
    await screen.findByText('Connect a channel');
    expect(screen.getByRole('combobox', { name: 'Channel type' })).toHaveTextContent('Messenger');
  });

  it('channels page: Reconnect on a card that needs attention opens Replace token', async () => {
    render(<ChannelsPage />, 'on');
    await screen.findAllByText('Support line');
    await settle();
    fireEvent.click(screen.getByRole('button', { name: 'Reconnect' }));
    expect(await screen.findByText('Replace the token for Support line')).toBeInTheDocument();
  });

  it('record: the test result sits beside Test connection, not in a toast', async () => {
    const view = render(<ChannelFormView channelId="chn-1" initialEditing={false} />, 'on');
    await screen.findByText('Maju Trading Sdn Bhd');
    await settle();
    fireEvent.click(tabButton(view.container, 'Test connection'));
    expect(await screen.findByText(/Connection works\. Checked/)).toBeInTheDocument();
    answers.testOk = false;
    fireEvent.click(tabButton(view.container, 'Test connection'));
    expect(await screen.findByText('Access token expired or revoked.')).toBeInTheDocument();
    expect(calls.some((c) => String(c[0]).startsWith('toast.') && c[1] === 'Connection OK.')).toBe(false);
  });

  it('webhooks: the new secret shows once with Copy and the warning line', async () => {
    render(<WebhooksPanel scopeId="chn-1" channelId="chn-1" />, 'on');
    await screen.findAllByText('CRM sync');
    await settle();
    const menus = screen.getAllByRole('button', { name: /actions/i, hidden: true });
    fireEvent.pointerDown(menus[0], { button: 0, pointerType: 'mouse' });
    fireEvent.click(await screen.findByRole('menuitem', { name: /Rotate secret/ }));
    expect(await screen.findByText('Requests signed with the old secret will fail.')).toBeInTheDocument();
    fireEvent.click(button('Rotate secret'));
    await screen.findByText('New signing secret for CRM sync');
    expect(screen.getByLabelText('Signing secret')).toHaveValue('whsec_rotated0123456789b2d4');
    expect(screen.getByText("Copy it now. It won't be shown again.")).toBeInTheDocument();
    expect(button('Copy')).toBeInTheDocument();
  });

  it('wizard: a closed sign-in window is not an error; a blocked one says so in plain words', () => {
    expect(fxConnectNote('Signup cancelled.')).toEqual({ text: 'Connection cancelled.', tone: 'quiet' });
    expect(fxConnectNote('Popup blocked - allow popups for this site and try again.').text).toBe(
      'Your browser blocked the sign-in window. Allow pop-ups for this site, then try again.',
    );
    expect(fxConnectNote('Meta said no.')).toEqual({ text: 'Meta said no.', tone: 'why' });
  });

  it('wizard: a new web chat secret shows once', async () => {
    render(<ChannelConnectWizard open onOpenChange={() => undefined} initialType="WEBCHAT" />, 'on');
    await screen.findByText('Connect a channel');
    await settle();
    fireEvent.change(screen.getByPlaceholderText('Website chat'), { target: { value: 'Maju site' } });
    const origin = screen.getByRole('textbox', { name: /origin/i });
    fireEvent.change(origin, { target: { value: 'https://maju.example' } });
    fireEvent.keyDown(origin, { key: 'Enter' });
    await settle();
    fireEvent.click(button('Connect web chat'));
    await screen.findByText('Web chat connected');
    expect(screen.getByLabelText('Widget secret')).toHaveValue('wsec_live_0123456789abcdefa91c');
    expect(screen.getByText("Copy it now. It won't be shown again.")).toBeInTheDocument();
  });

  it('template builder: Submit template is the one red action, naming the template', async () => {
    render(<TemplateBuilderView channelId="chn-1" templateId="tpl-1" />, 'on');
    const submit = await screen.findByRole('button', { name: 'Submit order_update to WhatsApp for review' });
    expect(submit).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /View payload/, hidden: true })).toBeInTheDocument();
  });

  it('template builder: leaving with changes asks to discard them by name', async () => {
    const view = render(<TemplateBuilderView channelId="chn-1" templateId="tpl-1" />, 'on');
    await screen.findByRole('button', { name: 'Submit order_update to WhatsApp for review' });
    const body = view.container.querySelector('textarea') as HTMLTextAreaElement;
    fireEvent.change(body, { target: { value: 'Changed text here.' } });
    fireEvent.click(button(/Back to channel/));
    expect(await screen.findByText('Discard changes to order_update?')).toBeInTheDocument();
    fireEvent.click(button('Discard changes'));
    expect(calls).toContainEqual(['router.push', '/omnichannel/settings/channels/chn-1']);
  });

  it('bubble preview: theme tokens, no raw WhatsApp colours', () => {
    const { container } = render(<WaBubblePreview doc={templateDetail().doc} />, 'on');
    const html = container.innerHTML;
    expect(html).not.toContain('#E5DDD5');
    expect(html).not.toContain('#00A5F4');
    expect(html).toContain('bg-(--fx-surface-2)');
  });

  it('WhatsApp callback: new words, the same message to the opener', async () => {
    const postMessage = vi.fn();
    const close = vi.spyOn(window, 'close').mockImplementation(() => undefined);
    Object.defineProperty(window, 'opener', { value: { postMessage }, configurable: true });
    window.history.replaceState(null, '', '/wa-callback?code=abc123');
    render(<WaCallbackPage />, 'on');
    await screen.findByText('Done. You can close this window.');
    expect(postMessage.mock.calls).toEqual([[{ type: 'FX_WA_OAUTH', code: 'abc123' }, window.location.origin]]);
    Object.defineProperty(window, 'opener', { value: null, configurable: true });
    close.mockRestore();
    window.history.replaceState(null, '', '/');
    await act(async () => undefined);
  });
});
