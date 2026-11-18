'use client';

/**
 * The connect wizard with the Foundryx UIUX switch on (gap audit 12,
 * "Connected services"). Same steps and the same requests as the legacy
 * wizard (both read `useChannelConnectWizard`); only the words and the look
 * change:
 * - while the provider's sign-in window is open: "Finish in the WhatsApp
 *   window.";
 * - a closed window is not an error: the first step comes back with
 *   "Connection cancelled." under its button;
 * - a blocked window and the provider's own errors show in plain words under
 *   the button, which reads "Try again";
 * - a new web chat secret shows once (`FxSecretOnce`); a pasted token is a
 *   password field with the eye (`FxSecretInput`).
 * The simulated sandbox popup (no Meta app configured) is the stand-in for
 * the provider's own window and keeps its look.
 */
import type { ReactNode } from 'react';
import { CheckCircle2, Inbox, Loader2 } from 'lucide-react';
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { SearchSelect } from '@/components/platform/search-select';
import { FxBlockedArea } from '@/components/fx/banners/blocked-area';
import { FxSecretInput, FxSecretOnce } from '@/components/fx/fields';
import { CHANNEL_CAPABILITIES, CHANNEL_TYPES } from '@/lib/channel-capabilities';
import { OriginsEditor } from '@/app/(protected)/omnichannel/settings/embed/origins-editor';
import type { ChannelType } from '@/types/omnichannel';
import type { ChannelConnectWizardProps } from './channel-connect-wizard';
import { MockEmbeddedSignupDialog } from './mock-embedded-signup-dialog';
import { useChannelConnectWizard } from './use-channel-connect-wizard';
import {
  FX_DIALOG_CLASS,
  FX_DIALOG_TITLE_CLASS,
  FX_LABEL_CLASS,
  FxDialogFooter,
  FxHideMainWhile,
  type FxDialogFooterProps,
} from './fx-dialog-parts';

const TYPE_OPTIONS = CHANNEL_TYPES.map((t) => ({ value: t, label: CHANNEL_CAPABILITIES[t].label }));

/** The two messages `launchEmbeddedSignup` raises itself (lib/embedded-signup.ts). */
export const SIGNUP_CANCELLED = 'Signup cancelled.';
export const POPUP_BLOCKED = 'Popup blocked - allow popups for this site and try again.';

/** The line under the button after a failed attempt, in the playbook's words. */
export function fxConnectNote(error: string | null): NonNullable<FxDialogFooterProps['note']> {
  if (!error || error === SIGNUP_CANCELLED) return { text: 'Connection cancelled.', tone: 'quiet' };
  if (error === POPUP_BLOCKED) {
    return {
      text: 'Your browser blocked the sign-in window. Allow pop-ups for this site, then try again.',
      tone: 'why',
    };
  }
  return { text: error, tone: 'why' };
}

/** The first step's button: verb + object. */
export function fxConnectLabel(type: ChannelType, configured: boolean): string {
  if (type === 'WEBCHAT') return 'Connect web chat';
  return configured ? `Connect ${CHANNEL_CAPABILITIES[type].label}` : 'Create sandbox channel';
}

export function FxChannelConnectWizard({
  open,
  onOpenChange,
  workspaceId,
  initialType,
  onConnected,
}: ChannelConnectWizardProps) {
  const w = useChannelConnectWizard({ open, workspaceId, initialType });
  const label = w.capabilities.label;
  const close = () => onOpenChange(false);

  if (open && w.isWhatsApp && !w.configured && (w.state === 'selecting' || w.state === 'exchanging')) {
    return (
      <MockEmbeddedSignupDialog
        open
        busy={w.state === 'exchanging'}
        onAuthorizeWaba={(opt) => w.authorize(opt).then(() => undefined)}
        onCancel={w.cancel}
      />
    );
  }

  const failed = w.state === 'failed';
  const failNote = failed ? fxConnectNote(w.error) : null;

  let title: string;
  let body: ReactNode = null;
  let footer: ReactNode = null;

  if (w.state === 'connected' && w.channel) {
    const channel = w.channel;
    title = w.isWebchat || w.configured ? `${label} connected` : 'Sandbox channel created';
    body = (
      <div className="flex flex-col gap-3">
        <div className="flex items-center gap-3 rounded-(--fx-r-m) border border-(--fx-line) p-3">
          <CheckCircle2
            aria-hidden="true"
            className={w.isWebchat || w.configured ? 'size-6 text-(--fx-ok)' : 'size-6 text-(--fx-warn)'}
          />
          <div className="min-w-0">
            <p className="text-sm font-semibold text-(--fx-ink)">{channel.name}</p>
            <p className="text-sm text-(--fx-ink-2)">
              {channel.displayPhoneNumber ?? channel.externalAccountName ?? channel.workspaceName}
            </p>
          </div>
        </div>
        {!w.isWebchat && !w.configured && (
          <p className="text-sm text-(--fx-warn-ink)">Not linked to a real Meta account.</p>
        )}
        {w.warnings.map((warning) => (
          <p key={warning} className="text-sm text-(--fx-warn-ink)">
            {warning}
          </p>
        ))}
        {w.isWebchat && w.webchatSecret && (
          <div className="flex flex-col gap-1.5">
            <span className={FX_LABEL_CLASS}>Widget secret</span>
            <FxSecretOnce value={w.webchatSecret} label="Widget secret" />
          </div>
        )}
      </div>
    );
    footer = (
      <FxDialogFooter
        action={{
          label: 'Done',
          onClick: () => {
            onConnected?.(channel);
            close();
          },
        }}
      />
    );
  } else if (w.popupOpen) {
    title = `Finish in the ${label} window.`;
    body = (
      <div className="flex justify-center py-6">
        <Loader2 aria-hidden="true" className="size-7 animate-spin text-(--fx-ink-3)" />
      </div>
    );
  } else if (w.state === 'authorizing' || w.state === 'exchanging') {
    title = `Connecting ${label}`;
    body = (
      <div className="flex justify-center py-6">
        <Loader2 aria-label={`Connecting ${label}`} className="size-7 animate-spin text-(--fx-ink-3)" />
      </div>
    );
  } else if (w.state === 'picking-page') {
    const isIg = w.channelType === 'INSTAGRAM';
    title = isIg ? 'Choose the Instagram account' : 'Choose the Facebook Page';
    body =
      w.availablePages.length === 0 ? (
        <div
          className="flex flex-col items-center gap-2 py-6 text-(--fx-ink-2)"
          data-testid="wizard-no-available-pages"
        >
          <Inbox aria-hidden="true" className="size-7" />
          <p className="text-sm">Every {isIg ? 'account' : 'Page'} is already connected.</p>
        </div>
      ) : (
        <SearchSelect
          options={w.availablePages.map((p) => ({
            value: p.id,
            label: isIg ? (p.igUsername ?? p.name) : p.name,
          }))}
          value={w.selectedPageId || null}
          onChange={w.setSelectedPageId}
          placeholder={isIg ? 'Select an account' : 'Select a page'}
          ariaLabel={isIg ? 'Instagram account' : 'Facebook Page'}
          className="w-full"
        />
      );
    footer = (
      <FxDialogFooter
        safe={{ label: 'Cancel', onClick: close }}
        action={
          w.availablePages.length > 0
            ? {
                label: w.selectedPage ? `Connect ${w.selectedPage.name}` : 'Connect',
                onClick: w.submitPage,
                disabled: !w.selectedPage,
              }
            : undefined
        }
      />
    );
  } else if (w.manualMode) {
    title = 'Connect with a token';
    body = (
      <div className="flex flex-col gap-3">
        {!workspaceId && (
          <div className="flex flex-col gap-1.5">
            <span className={FX_LABEL_CLASS}>Attach to workspace</span>
            <SearchSelect
              options={w.workspaces.map((ws) => ({ value: ws.id, label: ws.name }))}
              value={w.chosenWorkspace || null}
              onChange={w.setChosenWorkspace}
              placeholder="Select a workspace"
              ariaLabel="Workspace"
              className="w-full"
            />
          </div>
        )}
        <div className="flex flex-col gap-1.5">
          <label htmlFor="fx-manual-access-token" className={FX_LABEL_CLASS}>
            Permanent access token (System User)
          </label>
          <FxSecretInput
            id="fx-manual-access-token"
            autoComplete="off"
            value={w.manual.accessToken}
            onChange={(e) => w.setManual((m) => ({ ...m, accessToken: e.target.value }))}
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <label htmlFor="fx-manual-phone-id" className={FX_LABEL_CLASS}>
            Phone Number ID
          </label>
          <Input
            id="fx-manual-phone-id"
            value={w.manual.phoneNumberId}
            onChange={(e) => w.setManual((m) => ({ ...m, phoneNumberId: e.target.value }))}
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <label htmlFor="fx-manual-waba-id" className={FX_LABEL_CLASS}>
            WABA ID (optional)
          </label>
          <Input
            id="fx-manual-waba-id"
            value={w.manual.wabaId}
            onChange={(e) => w.setManual((m) => ({ ...m, wabaId: e.target.value }))}
          />
        </div>
      </div>
    );
    footer = (
      <FxDialogFooter
        safe={{ label: 'Back', onClick: () => w.setManualMode(false) }}
        action={{
          label: failed ? 'Try again' : 'Connect WhatsApp',
          onClick: w.submitManual,
          disabled: !w.manualValid || !w.chosenWorkspace,
        }}
        note={failNote}
      />
    );
  } else {
    title = 'Connect a channel';
    body = (
      <div className="flex flex-col gap-4">
        <div className="flex flex-col gap-1.5">
          <span className={FX_LABEL_CLASS}>Channel type</span>
          <SearchSelect
            options={TYPE_OPTIONS}
            value={w.channelType}
            onChange={(v) => w.setChannelType(v as ChannelType)}
            ariaLabel="Channel type"
            className="w-full"
          />
        </div>
        {!workspaceId && (
          <div className="flex flex-col gap-1.5">
            <span className={FX_LABEL_CLASS}>Attach to workspace</span>
            <SearchSelect
              options={w.workspaces.map((ws) => ({ value: ws.id, label: ws.name }))}
              value={w.chosenWorkspace || null}
              onChange={w.setChosenWorkspace}
              placeholder="Select a workspace"
              ariaLabel="Workspace"
              className="w-full"
            />
          </div>
        )}
        {w.isWebchat ? (
          <>
            <div className="flex flex-col gap-1.5">
              <label htmlFor="fx-webchat-name" className={FX_LABEL_CLASS}>
                Channel name
              </label>
              <Input
                id="fx-webchat-name"
                placeholder="Website chat"
                value={w.webchatName}
                onChange={(e) => w.setWebchatName(e.target.value)}
              />
            </div>
            <OriginsEditor origins={w.webchatOrigins} onChange={w.setWebchatOrigins} bare />
          </>
        ) : (
          <>
            {!w.configured && (
              <FxBlockedArea>
                {label} is not set up here for real connections, so this makes a sandbox channel.
              </FxBlockedArea>
            )}
            {w.isWhatsApp && (
              <Button
                type="button"
                variant="fx-text"
                size="sm"
                className="self-start px-0"
                onClick={() => w.setManualMode(true)}
              >
                Connect with a token instead
              </Button>
            )}
          </>
        )}
      </div>
    );
    const Icon = w.capabilities.icon;
    footer = (
      <FxDialogFooter
        safe={{ label: 'Cancel', onClick: close }}
        action={{
          label: failed ? 'Try again' : fxConnectLabel(w.channelType, w.configured),
          onClick: () => void w.handleConnect(),
          disabled: !w.chosenWorkspace || (w.isWebchat ? !w.webchatValid : false),
          icon: <Icon aria-hidden="true" className="size-4" />,
        }}
        note={failNote}
      />
    );
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !o && close()}>
      <FxHideMainWhile open={open} />
      <DialogContent className={FX_DIALOG_CLASS} data-fx-connect-wizard="">
        <DialogTitle className={FX_DIALOG_TITLE_CLASS}>{title}</DialogTitle>
        <DialogDescription className="sr-only">{title}</DialogDescription>
        {body}
        {footer}
      </DialogContent>
    </Dialog>
  );
}
