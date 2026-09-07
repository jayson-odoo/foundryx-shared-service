'use client';

import { useEffect, useState } from 'react';
import { CheckCircle2, Inbox, Loader2, TriangleAlert } from 'lucide-react';
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { SearchSelect } from '@/components/platform/search-select';
import { useConnectChannel } from '@/hooks/use-connect-channel';
import { workspaceService } from '@/services/workspace-service';
import { PRESSED_CLASS } from '@/components/ui/primitive-classes';
import { isEmbeddedSignupConfigured, launchEmbeddedSignup } from '@/lib/embedded-signup';
import { CHANNEL_CAPABILITIES, CHANNEL_TYPES } from '@/lib/channel-capabilities';
import { cn } from '@/lib/utils';
import type { Channel, ChannelType, Workspace } from '@/types/omnichannel';
import { OriginsEditor } from '@/app/(protected)/omnichannel/settings/embed/origins-editor';
import { CopyField } from '@/app/(protected)/omnichannel/settings/embed/copy-field';
import { MockEmbeddedSignupDialog } from './mock-embedded-signup-dialog';

export interface ChannelConnectWizardProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Fix the target workspace (e.g. launched from a workspace page); otherwise the
   *  wizard offers a workspace picker. */
  workspaceId?: string;
  /** Called when a channel is successfully provisioned (e.g. to reload a list). */
  onConnected?: (channel: Channel) => void;
}

const TYPE_OPTIONS = CHANNEL_TYPES.map((t) => ({ value: t, label: CHANNEL_CAPABILITIES[t].label }));

/**
 * Reusable channel onboarding wizard (plan 04 §5, §7; extended plan 32 / A7a
 * for Messenger + Instagram). Drives the connect flow end to end:
 *
 *   type + workspace → "Continue" → [Meta popup] → (Messenger/Instagram: pick
 *   a page) → exchanging → connected | failed
 *
 * When the Meta app is configured the real Embedded Signup / Business Login
 * SDK launches; when unset (dev / no Meta app yet) it falls back to a
 * simulated popup so local dev + tests work without a Meta app - for all
 * three channel types (AC-CHN-03), never a parallel dialog.
 */
export function ChannelConnectWizard({
  open,
  onOpenChange,
  workspaceId,
  onConnected,
}: ChannelConnectWizardProps) {
  const [channelType, setChannelType] = useState<ChannelType>('WHATSAPP');
  const [selectedPageId, setSelectedPageId] = useState<string>('');
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [chosenWorkspace, setChosenWorkspace] = useState<string>(workspaceId ?? '');
  const [manualMode, setManualMode] = useState(false);
  const [manual, setManual] = useState({ accessToken: '', phoneNumberId: '', wabaId: '', phoneNumber: '' });
  // Web chat (plan 34 / A7b, AC-WEB-01/02) - no OAuth, no page selection; just
  // a name + at least one allowed origin, staged in the origins editor's
  // controlled mode until "Connect" submits everything together.
  const [webchatName, setWebchatName] = useState('');
  const [webchatOrigins, setWebchatOrigins] = useState<string[]>([]);
  const {
    state,
    channel,
    error,
    pages,
    webchatSecret,
    start,
    cancel,
    authorize,
    completeWithResult,
    connectManual,
    setExchanging,
    fail,
    reset,
    startMetaAuth,
    authorizeMetaCode,
    selectMetaPage,
    connectWebchat,
  } = useConnectChannel(chosenWorkspace);
  const configured = isEmbeddedSignupConfigured();
  const capabilities = CHANNEL_CAPABILITIES[channelType];
  const isWhatsApp = channelType === 'WHATSAPP';
  const isWebchat = channelType === 'WEBCHAT';
  const manualValid = manual.accessToken.trim().length > 0 && manual.phoneNumberId.trim().length > 0;
  const webchatValid = webchatName.trim().length > 0 && webchatOrigins.length > 0;
  const availablePages = pages.filter((p) => !p.connected);
  const selectedPage = availablePages.find((p) => p.id === selectedPageId) ?? null;

  // "Continue" - real SDK/OAuth when configured, else the simulated popup.
  const handleConnect = async () => {
    if (isWebchat) {
      if (!webchatValid) return;
      void connectWebchat({
        name: webchatName.trim(),
        workspaceId: chosenWorkspace,
        allowedOrigins: webchatOrigins,
      });
      return;
    }
    if (isWhatsApp) {
      if (!configured) {
        start();
        return;
      }
      setExchanging();
      try {
        const result = await launchEmbeddedSignup('WHATSAPP');
        await completeWithResult(result);
      } catch (e) {
        fail(e instanceof Error ? e.message : 'Signup failed. Please try again.');
      }
      return;
    }
    startMetaAuth();
    if (!configured) {
      // Simulated authorize (dev / no Meta app configured, AC-CHN-03) - the
      // dev-safe backend adapter ignores the code and returns the SAME
      // canned sandbox pages for any value, so this reuses the real two-call
      // flow (`listMetaPages` -> pick -> `connectMetaChannel`) instead of a
      // parallel mock data source. The "picking a page" step right after IS
      // the simulated popup's job here (no separate mock dialog for Meta
      // types, matching the WhatsApp mock's "pick, then authorize" shape).
      await authorizeMetaCode(channelType, `simulated-${Date.now()}`);
      return;
    }
    try {
      const result = await launchEmbeddedSignup(channelType);
      await authorizeMetaCode(channelType, result.code, result.redirectUri);
    } catch (e) {
      fail(e instanceof Error ? e.message : 'Authorization failed. Please try again.');
    }
  };

  // Load workspaces for the picker (only when no fixed workspace).
  useEffect(() => {
    if (workspaceId) return;
    workspaceService
      .list({ page: 0, pageSize: 100, statusView: 'active' })
      .then((r) => {
        setWorkspaces(r.data);
        setChosenWorkspace((prev) => prev || r.data.find((w) => w.isDefault)?.id || r.data[0]?.id || '');
      })
      .catch(() => setWorkspaces([]));
  }, [workspaceId]);

  // Reset the flow whenever the wizard is (re)opened.
  useEffect(() => {
    if (open) {
      reset();
      setChannelType('WHATSAPP');
      setSelectedPageId('');
      setManualMode(false);
      setManual({ accessToken: '', phoneNumberId: '', wabaId: '', phoneNumber: '' });
      setWebchatName('');
      setWebchatOrigins([]);
    }
  }, [open, reset]);

  // Picking a different type mid-flow drops any in-progress page selection
  // or staged web chat fields (a stale name/origin list must not survive a
  // switch away from and back to Web chat).
  useEffect(() => {
    setSelectedPageId('');
    setWebchatName('');
    setWebchatOrigins([]);
  }, [channelType]);

  const submitManual = () => {
    if (!manualValid || !chosenWorkspace) return;
    void connectManual({
      workspaceId: chosenWorkspace,
      accessToken: manual.accessToken.trim(),
      phoneNumberId: manual.phoneNumberId.trim(),
      wabaId: manual.wabaId.trim() || undefined,
      phoneNumber: manual.phoneNumber.trim() || undefined,
    });
  };

  const close = () => {
    onOpenChange(false);
  };

  const handleConnected = (c: Channel) => {
    onConnected?.(c);
  };

  const submitPage = () => {
    if (!selectedPage) return;
    void selectMetaPage(channelType, chosenWorkspace, selectedPage);
  };

  // Simulated WhatsApp popup (dev / no Meta app) - picking a WABA number IS
  // the authorization there (unchanged, plan 04). Messenger/Instagram never
  // reach `selecting` (their simulated path reuses the real two-call flow -
  // `startMetaAuth` -> `authorizing`/`picking-page`/`exchanging` below).
  if (open && isWhatsApp && !configured && (state === 'selecting' || state === 'exchanging')) {
    return (
      <MockEmbeddedSignupDialog
        open
        busy={state === 'exchanging'}
        onAuthorizeWaba={(opt) => authorize(opt).then(() => undefined)}
        onCancel={cancel}
      />
    );
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !o && close()}>
      <DialogContent className="w-full max-w-[460px]">
        {state === 'connected' && channel ? (
          <>
            <DialogHeader>
              <DialogTitle>
                {isWebchat ? 'Channel connected' : configured ? 'Channel connected' : 'Sandbox channel created'}
              </DialogTitle>
              <DialogDescription>
                {isWebchat
                  ? `Your ${capabilities.label} channel is ready to use.`
                  : configured
                    ? `Your ${capabilities.label} channel is ready to use.`
                    : 'Simulated channel - not linked to a real Meta account.'}
              </DialogDescription>
            </DialogHeader>
            <DialogBody className="flex flex-col items-center gap-3 py-4 text-center">
              <CheckCircle2
                className={isWebchat || configured ? 'size-12 text-green-600' : 'size-12 text-amber-500'}
              />
              <div>
                <p className="text-sm font-medium text-foreground">{channel.name}</p>
                <p className="text-xs text-muted-foreground">
                  {channel.displayPhoneNumber ?? channel.externalAccountName}
                </p>
              </div>
              {isWebchat && webchatSecret && (
                <div className="w-full text-left">
                  <label className="text-xs text-muted-foreground">Widget secret</label>
                  <CopyField value={webchatSecret} ariaLabel="Widget secret" />
                </div>
              )}
            </DialogBody>
            <DialogFooter>
              <Button
                onClick={() => {
                  handleConnected(channel);
                  close();
                }}
              >
                Done
              </Button>
            </DialogFooter>
          </>
        ) : state === 'failed' ? (
          <>
            <DialogHeader>
              <DialogTitle>Connection failed</DialogTitle>
              <DialogDescription>We couldn&apos;t connect the channel.</DialogDescription>
            </DialogHeader>
            <DialogBody className="flex flex-col items-center gap-3 py-4 text-center">
              <TriangleAlert className="size-12 text-destructive" />
              <p className="text-sm text-muted-foreground">{error}</p>
            </DialogBody>
            <DialogFooter>
              <Button variant="outline" onClick={close}>
                Close
              </Button>
              <Button onClick={handleConnect}>Try again</Button>
            </DialogFooter>
          </>
        ) : state === 'authorizing' || state === 'exchanging' ? (
          // Real SDK path: popup handed back, backend exchanging the code / pages.
          <>
            <DialogHeader>
              <DialogTitle>Connecting…</DialogTitle>
              <DialogDescription>Finalising your {capabilities.label} connection.</DialogDescription>
            </DialogHeader>
            <DialogBody className="flex items-center justify-center py-10">
              <Loader2 className="size-8 animate-spin text-muted-foreground" />
            </DialogBody>
          </>
        ) : state === 'picking-page' ? (
          // Real path only - the wizard's own page-selection step (AC-CHN-02).
          <>
            <DialogHeader>
              <DialogTitle>
                Choose a {channelType === 'INSTAGRAM' ? 'professional account' : 'Page'}
              </DialogTitle>
              <DialogDescription>
                {channelType === 'INSTAGRAM'
                  ? 'Pick the Instagram professional account to connect.'
                  : 'Pick the Facebook Page to connect.'}
              </DialogDescription>
            </DialogHeader>
            <DialogBody className="flex flex-col gap-3">
              {availablePages.length === 0 ? (
                // Every returned page/account is already connected (nit,
                // security review round 1) - foolproof-UI: never leave an
                // empty picker + a permanently-disabled Connect button with
                // no explanation of the CURRENT STATE (distinct from the
                // house's "no instructional copy" rule, which forbids
                // teaching how to use the screen, not stating a fact).
                <div
                  className="flex flex-col items-center justify-center gap-2 py-6 text-muted-foreground"
                  data-testid="wizard-no-available-pages"
                >
                  <Inbox className="size-8" />
                  <p className="text-sm">
                    Every {channelType === 'INSTAGRAM' ? 'account' : 'Page'} is already connected.
                  </p>
                </div>
              ) : (
                <SearchSelect
                  options={availablePages.map((p) => ({
                    value: p.id,
                    label: channelType === 'INSTAGRAM' ? (p.igUsername ?? p.name) : p.name,
                  }))}
                  value={selectedPageId || null}
                  onChange={setSelectedPageId}
                  placeholder={channelType === 'INSTAGRAM' ? 'Select an account' : 'Select a page'}
                  ariaLabel={channelType === 'INSTAGRAM' ? 'Instagram account' : 'Facebook Page'}
                  className="w-full"
                />
              )}
            </DialogBody>
            <DialogFooter>
              <Button variant="outline" onClick={close}>
                Cancel
              </Button>
              {availablePages.length > 0 && (
                <Button onClick={submitPage} disabled={!selectedPage}>
                  Connect
                </Button>
              )}
            </DialogFooter>
          </>
        ) : manualMode ? (
          // Manual connect - paste a System User token + phone number id (WhatsApp only).
          <>
            <DialogHeader>
              <DialogTitle>Set up manually</DialogTitle>
              <DialogDescription>
                Paste a permanent System User token + Phone Number ID (from the WhatsApp API
                Setup page). We validate it against Meta before connecting.
              </DialogDescription>
            </DialogHeader>
            <DialogBody className="flex flex-col gap-3">
              {!workspaceId && (
                <div className="flex flex-col gap-1.5">
                  <label className="text-sm text-muted-foreground">Attach to workspace</label>
                  <SearchSelect
                    options={workspaces.map((w) => ({ value: w.id, label: w.name }))}
                    value={chosenWorkspace || null}
                    onChange={setChosenWorkspace}
                    placeholder="Select a workspace"
                    ariaLabel="Workspace"
                    className="w-full"
                  />
                </div>
              )}
              <div className="flex flex-col gap-1.5">
                <label className="text-sm text-muted-foreground">System User token *</label>
                <Input
                  placeholder="EAAG…"
                  value={manual.accessToken}
                  onChange={(e) => setManual((m) => ({ ...m, accessToken: e.target.value }))}
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <label className="text-sm text-muted-foreground">Phone Number ID *</label>
                <Input
                  placeholder="e.g. 123456789012345"
                  value={manual.phoneNumberId}
                  onChange={(e) => setManual((m) => ({ ...m, phoneNumberId: e.target.value }))}
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <label className="text-sm text-muted-foreground">WABA ID (optional)</label>
                <Input
                  placeholder="WhatsApp Business Account ID"
                  value={manual.wabaId}
                  onChange={(e) => setManual((m) => ({ ...m, wabaId: e.target.value }))}
                />
              </div>
            </DialogBody>
            <DialogFooter>
              <Button variant="outline" onClick={() => setManualMode(false)}>
                Back
              </Button>
              <Button onClick={submitManual} disabled={!manualValid || !chosenWorkspace}>
                Connect
              </Button>
            </DialogFooter>
          </>
        ) : (
          // intro - channel type + workspace
          <>
            <DialogHeader>
              <DialogTitle>Connect a channel</DialogTitle>
              <DialogDescription>
                Choose what to connect. No technical setup - pick your channel in the popup.
              </DialogDescription>
            </DialogHeader>
            <DialogBody className="flex flex-col gap-4">
              <div className="flex flex-col gap-1.5">
                <label className="text-sm text-muted-foreground">Channel type</label>
                <SearchSelect
                  options={TYPE_OPTIONS}
                  value={channelType}
                  onChange={(v) => setChannelType(v as ChannelType)}
                  ariaLabel="Channel type"
                  className="w-full"
                />
              </div>
              {!workspaceId && (
                <div className="flex flex-col gap-1.5">
                  <label className="text-sm text-muted-foreground">Attach to workspace</label>
                  <SearchSelect
                    options={workspaces.map((w) => ({ value: w.id, label: w.name }))}
                    value={chosenWorkspace || null}
                    onChange={setChosenWorkspace}
                    placeholder="Select a workspace"
                    ariaLabel="Workspace"
                    className="w-full"
                  />
                </div>
              )}
              {isWebchat ? (
                <>
                  <div className="flex flex-col gap-1.5">
                    <label className="text-sm text-muted-foreground">Channel name</label>
                    <Input
                      placeholder="Website chat"
                      value={webchatName}
                      onChange={(e) => setWebchatName(e.target.value)}
                    />
                  </div>
                  <OriginsEditor origins={webchatOrigins} onChange={setWebchatOrigins} bare />
                </>
              ) : (
                <>
                  {!configured && (
                    <div className="flex items-start gap-2 rounded-md border border-amber-300 bg-amber-50 p-3 text-xs text-amber-900">
                      <TriangleAlert className="mt-0.5 size-4 shrink-0 text-amber-600" />
                      <span>
                        {capabilities.label} app not configured - this creates a{' '}
                        <strong>simulated sandbox channel</strong>, not a real connection.
                      </span>
                    </div>
                  )}
                  {isWhatsApp && (
                    <button
                      type="button"
                      className={cn(PRESSED_CLASS, 'self-start text-xs font-medium text-primary hover:underline')}
                      onClick={() => setManualMode(true)}
                    >
                      Set up manually (paste token)
                    </button>
                  )}
                </>
              )}
            </DialogBody>
            <DialogFooter>
              <Button variant="outline" onClick={close}>
                Cancel
              </Button>
              <Button
                onClick={handleConnect}
                disabled={!chosenWorkspace || (isWebchat ? !webchatValid : false)}
              >
                <capabilities.icon className="size-4" />
                {isWebchat ? 'Connect' : configured ? 'Continue' : 'Connect (sandbox)'}
              </Button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
