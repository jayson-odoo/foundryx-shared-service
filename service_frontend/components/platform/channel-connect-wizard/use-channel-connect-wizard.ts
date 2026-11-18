'use client';

import { useEffect, useState } from 'react';
import { useConnectChannel } from '@/hooks/use-connect-channel';
import { useDatetime } from '@/hooks/use-datetime';
import { tokenWarnings } from '@/lib/channel-token-warnings';
import { workspaceService } from '@/services/workspace-service';
import { isEmbeddedSignupConfigured, launchEmbeddedSignup } from '@/lib/embedded-signup';
import { CHANNEL_CAPABILITIES } from '@/lib/channel-capabilities';
import type { ChannelType, Workspace } from '@/types/omnichannel';

export interface UseChannelConnectWizardOptions {
  open: boolean;
  workspaceId?: string;
  /** The channel type picked when the wizard opens (default WhatsApp). */
  initialType?: ChannelType;
}

/**
 * The connect wizard's state and steps, shared by both looks (Foundryx UIUX
 * switch off and on) so the two cannot drift in what they send. Moved out of
 * `channel-connect-wizard.tsx` unchanged; only `popupOpen` is new, and it only
 * tracks whether the sign-in window is showing (nothing reads it with the
 * switch off).
 */
export function useChannelConnectWizard({ open, workspaceId, initialType }: UseChannelConnectWizardOptions) {
  const [channelType, setChannelType] = useState<ChannelType>(initialType ?? 'WHATSAPP');
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
  // True while the provider's sign-in window is open (real path only).
  const [popupOpen, setPopupOpen] = useState(false);
  const connect = useConnectChannel(chosenWorkspace);
  const {
    channel,
    pages,
    start,
    completeWithResult,
    connectManual,
    setExchanging,
    fail,
    reset,
    startMetaAuth,
    authorizeMetaCode,
    selectMetaPage,
    connectWebchat,
  } = connect;
  const configured = isEmbeddedSignupConfigured();
  const capabilities = CHANNEL_CAPABILITIES[channelType];
  const isWhatsApp = channelType === 'WHATSAPP';
  const isWebchat = channelType === 'WEBCHAT';
  const manualValid = manual.accessToken.trim().length > 0 && manual.phoneNumberId.trim().length > 0;
  const webchatValid = webchatName.trim().length > 0 && webchatOrigins.length > 0;
  const { formatDate } = useDatetime();
  const warnings = channel ? tokenWarnings({ tokenExpiresAt: channel.tokenExpiresAt }, formatDate) : [];
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
        setPopupOpen(true);
        let result;
        try {
          result = await launchEmbeddedSignup('WHATSAPP');
        } finally {
          setPopupOpen(false);
        }
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
      setPopupOpen(true);
      let result;
      try {
        result = await launchEmbeddedSignup(channelType);
      } finally {
        setPopupOpen(false);
      }
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
      setChannelType(initialType ?? 'WHATSAPP');
      setSelectedPageId('');
      setManualMode(false);
      setManual({ accessToken: '', phoneNumberId: '', wabaId: '', phoneNumber: '' });
      setWebchatName('');
      setWebchatOrigins([]);
    }
  }, [open, reset, initialType]);

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

  const submitPage = () => {
    if (!selectedPage) return;
    void selectMetaPage(channelType, chosenWorkspace, selectedPage);
  };

  return {
    ...connect,
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
    popupOpen,
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
  };
}

export type ChannelConnectWizardState = ReturnType<typeof useChannelConnectWizard>;
