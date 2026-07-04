'use client';

import { useState } from 'react';
import { LoaderCircleIcon, Send } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { useCan } from '@/hooks/use-can';
import { personaService } from '@/services/persona-service';
import type { PortalInviteInput } from '@/types/persona';

/**
 * Staff "Send portal invite" trigger (AC-06-15c). Issues a single-use
 * set-password link to a Profile's email (optionally carrying a persona grant
 * applied on acceptance). Gated personas.manage (UX; the backend is the real
 * boundary). Disabled — not hidden — when the profile has no email, so the
 * reason is self-evident (foolproof-UI).
 */
export interface PortalInviteButtonProps {
  profileId: string;
  /** The profile's email — drives the disabled state (no email = can't invite). */
  email?: string | null;
  /** Optional persona grant to ride the invite (granted on acceptance). */
  grant?: PortalInviteInput;
  size?: 'sm' | 'md';
  variant?: 'primary' | 'outline' | 'ghost';
}

export function PortalInviteButton({
  profileId,
  email,
  grant,
  size = 'sm',
  variant = 'outline',
}: PortalInviteButtonProps) {
  const { can } = useCan();
  const [sending, setSending] = useState(false);

  if (!can('personas.manage')) return null;

  const hasEmail = Boolean((email ?? '').trim());

  const send = async () => {
    setSending(true);
    try {
      const res = await personaService.sendPortalInvite(profileId, grant);
      toast.success(`Portal invite sent to ${res.email}.`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not send the invite.');
    } finally {
      setSending(false);
    }
  };

  return (
    <Button
      variant={variant}
      size={size}
      disabled={!hasEmail || sending}
      onClick={() => void send()}
    >
      {sending ? (
        <LoaderCircleIcon className="size-3.5 animate-spin" />
      ) : (
        <Send className="size-3.5" />
      )}
      Send portal invite
    </Button>
  );
}
