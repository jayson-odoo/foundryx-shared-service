'use client';

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
import { useFx } from '@/hooks/use-fx';
import { PRESSED_CLASS } from '@/components/ui/primitive-classes';
import { CHANNEL_CAPABILITIES, CHANNEL_TYPES } from '@/lib/channel-capabilities';
import { cn } from '@/lib/utils';
import type { Channel, ChannelType } from '@/types/omnichannel';
import { OriginsEditor } from '@/app/(protected)/omnichannel/settings/embed/origins-editor';
import { CopyField } from '@/app/(protected)/omnichannel/settings/embed/copy-field';
import { MockEmbeddedSignupDialog } from './mock-embedded-signup-dialog';
import { FxChannelConnectWizard } from './fx-channel-connect-wizard';
import { useChannelConnectWizard } from './use-channel-connect-wizard';

export interface ChannelConnectWizardProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Fix the target workspace (e.g. launched from a workspace page); otherwise the
   *  wizard offers a workspace picker. */
  workspaceId?: string;
  /** The channel type picked when the wizard opens (default WhatsApp). The
   *  type stays changeable. */
  initialType?: ChannelType;
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
export function ChannelConnectWizard(props: ChannelConnectWizardProps) {
  return useFx() ? <FxChannelConnectWizard {...props} /> : <ChannelConnectWizardLegacy {...props} />;
}

function ChannelConnectWizardLegacy({
  open,
  onOpenChange,
  workspaceId,
  initialType,
  onConnected,
}: ChannelConnectWizardProps) {
  const {
    channelType,
    setChannelType,
    selectedPageId,
    setSelectedPageId,
    workspaces,
    chosenWorkspace,
    setChosenWorkspace,
    manualMode,
    setManualMode,
    manual,
    setManual,
    webchatName,
    setWebchatName,
    webchatOrigins,
    setWebchatOrigins,
    state,
    channel,
    error,
    webchatSecret,
    cancel,
    authorize,
    configured,
    capabilities,
    isWhatsApp,
    isWebchat,
    manualValid,
    webchatValid,
    warnings,
    availablePages,
    selectedPage,
    handleConnect,
    submitManual,
    submitPage,
  } = useChannelConnectWizard({ open, workspaceId, initialType });

  const close = () => {
    onOpenChange(false);
  };

  const handleConnected = (c: Channel) => {
    onConnected?.(c);
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
              {warnings.length > 0 && (
                <div className="flex w-full flex-col gap-1 text-left">
                  {warnings.map((w) => (
                    <p key={w} className="text-xs text-amber-600">
                      {w}
                    </p>
                  ))}
                </div>
              )}
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
                <label htmlFor="manual-access-token" className="text-sm text-muted-foreground">
                  Permanent access token (System User)
                </label>
                <Input
                  id="manual-access-token"
                  type="password"
                  autoComplete="off"
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
