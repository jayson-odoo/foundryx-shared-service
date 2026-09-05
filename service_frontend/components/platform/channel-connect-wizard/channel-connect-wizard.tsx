'use client';

import { useEffect, useState } from 'react';
import { CheckCircle2, Facebook, Loader2, TriangleAlert } from 'lucide-react';
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { useConnectChannel } from '@/hooks/use-connect-channel';
import { workspaceService } from '@/services/workspace-service';
import { PRESSED_CLASS } from '@/components/ui/primitive-classes';
import { isEmbeddedSignupConfigured, launchEmbeddedSignup } from '@/lib/embedded-signup';
import { cn } from '@/lib/utils';
import type { Channel, Workspace } from '@/types/omnichannel';
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

/**
 * Reusable WhatsApp channel onboarding wizard (plan 04 §5, §7). Drives the
 * Embedded Signup flow end to end:
 *
 *   intro (pick workspace) → "Connect with Facebook" → [Meta popup] →
 *   exchanging → connected | failed
 *
 * When the Meta app is configured (NEXT_PUBLIC_META_APP_ID + config_id) the
 * "Connect with Facebook" button launches the REAL Embedded Signup SDK; when
 * unset (dev / no Meta app yet) it falls back to a simulated popup so local dev
 * + tests work without a Meta app.
 */
export function ChannelConnectWizard({
  open,
  onOpenChange,
  workspaceId,
  onConnected,
}: ChannelConnectWizardProps) {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [chosenWorkspace, setChosenWorkspace] = useState<string>(workspaceId ?? '');
  const [manualMode, setManualMode] = useState(false);
  const [manual, setManual] = useState({ accessToken: '', phoneNumberId: '', wabaId: '', phoneNumber: '' });
  const {
    state,
    channel,
    error,
    start,
    cancel,
    authorize,
    completeWithResult,
    connectManual,
    setExchanging,
    fail,
    reset,
  } = useConnectChannel(chosenWorkspace);
  const configured = isEmbeddedSignupConfigured();
  const manualValid = manual.accessToken.trim().length > 0 && manual.phoneNumberId.trim().length > 0;

  // "Connect with Facebook" - real SDK when configured, else the simulated popup.
  const handleConnect = async () => {
    if (!configured) {
      start();
      return;
    }
    setExchanging();
    try {
      const result = await launchEmbeddedSignup();
      await completeWithResult(result);
    } catch (e) {
      fail(e instanceof Error ? e.message : 'Signup failed. Please try again.');
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
      setManualMode(false);
      setManual({ accessToken: '', phoneNumberId: '', wabaId: '', phoneNumber: '' });
    }
  }, [open, reset]);

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

  // Simulated popup (dev / no Meta app) - selecting, or exchanging after a pick.
  if (open && !configured && (state === 'selecting' || state === 'exchanging')) {
    return (
      <MockEmbeddedSignupDialog
        open
        busy={state === 'exchanging'}
        onAuthorize={(opt) => authorize(opt).then(() => undefined)}
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
              <DialogTitle>{configured ? 'Channel connected' : 'Sandbox channel created'}</DialogTitle>
              <DialogDescription>
                {configured
                  ? 'Your WhatsApp number is ready to use.'
                  : 'Simulated channel - not linked to a real WhatsApp number.'}
              </DialogDescription>
            </DialogHeader>
            <DialogBody className="flex flex-col items-center gap-3 py-4 text-center">
              <CheckCircle2 className={configured ? 'size-12 text-green-600' : 'size-12 text-amber-500'} />
              <div>
                <p className="text-sm font-medium text-foreground">{channel.name}</p>
                <p className="text-xs text-muted-foreground">{channel.displayPhoneNumber}</p>
              </div>
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
        ) : state === 'exchanging' ? (
          // Real SDK path: popup handed back, backend exchanging the code.
          <>
            <DialogHeader>
              <DialogTitle>Connecting…</DialogTitle>
              <DialogDescription>Finalising your WhatsApp connection.</DialogDescription>
            </DialogHeader>
            <DialogBody className="flex items-center justify-center py-10">
              <Loader2 className="size-8 animate-spin text-muted-foreground" />
            </DialogBody>
          </>
        ) : manualMode ? (
          // Manual connect - paste a System User token + phone number id.
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
                  <Select value={chosenWorkspace} onValueChange={setChosenWorkspace}>
                    <SelectTrigger>
                      <SelectValue placeholder="Select a workspace" />
                    </SelectTrigger>
                    <SelectContent>
                      {workspaces.map((w) => (
                        <SelectItem key={w.id} value={w.id}>
                          {w.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
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
          // intro
          <>
            <DialogHeader>
              <DialogTitle>Connect a WhatsApp channel</DialogTitle>
              <DialogDescription>
                Connect your Meta-approved WhatsApp Business number through Facebook. No
                technical setup - pick your number in the popup.
              </DialogDescription>
            </DialogHeader>
            <DialogBody className="flex flex-col gap-4">
              {!workspaceId && (
                <div className="flex flex-col gap-1.5">
                  <label className="text-sm text-muted-foreground">Attach to workspace</label>
                  <Select value={chosenWorkspace} onValueChange={setChosenWorkspace}>
                    <SelectTrigger>
                      <SelectValue placeholder="Select a workspace" />
                    </SelectTrigger>
                    <SelectContent>
                      {workspaces.map((w) => (
                        <SelectItem key={w.id} value={w.id}>
                          {w.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              )}
              {!configured && (
                <div className="flex items-start gap-2 rounded-md border border-amber-300 bg-amber-50 p-3 text-xs text-amber-900">
                  <TriangleAlert className="mt-0.5 size-4 shrink-0 text-amber-600" />
                  <span>
                    WhatsApp app not configured - this creates a{' '}
                    <strong>simulated sandbox channel</strong>, not a real connection. Set the
                    Meta app credentials to enable real Embedded Signup.
                  </span>
                </div>
              )}
              <button
                type="button"
                className={cn(PRESSED_CLASS, 'self-start text-xs font-medium text-primary hover:underline')}
                onClick={() => setManualMode(true)}
              >
                Set up manually (paste token)
              </button>
            </DialogBody>
            <DialogFooter>
              <Button variant="outline" onClick={close}>
                Cancel
              </Button>
              <Button onClick={handleConnect} disabled={!chosenWorkspace}>
                <Facebook className="size-4" />
                {configured ? 'Connect with Facebook' : 'Connect (sandbox)'}
              </Button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
