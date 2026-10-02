'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import type { WebchatPreChatToggles, WebchatPreChatValues } from '@/types/omnichannel';
import { MessageText } from './message-text';

export interface PreChatStepProps {
  toggles: WebchatPreChatToggles;
  greeting: string;
  sending: boolean;
  error: string | null;
  honeypot: string;
  onHoneypotChange: (value: string) => void;
  onSubmit: (text: string, values: WebchatPreChatValues) => void;
}

/**
 * The fixed pre-chat capture step (D-A7B-23, AC-WEB-53) - only the toggles
 * the admin turned on render, and every field is OPTIONAL (a visitor can
 * always just send their message). Values ride along on the FIRST message
 * only, in the SAME request the composer would otherwise send
 * (D-A7B-8/D-A7B-54 - write-if-empty, never a lookup or a merge).
 */
export function PreChatStep({
  toggles,
  greeting,
  sending,
  error,
  honeypot,
  onHoneypotChange,
  onSubmit,
}: PreChatStepProps) {
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [phone, setPhone] = useState('');
  const [text, setText] = useState('');

  const canSend = text.trim().length > 0 && !sending;

  function submit() {
    if (!canSend) return;
    const values: WebchatPreChatValues = {};
    if (toggles.askName && name.trim()) values.name = name.trim();
    if (toggles.askEmail && email.trim()) values.email = email.trim();
    if (toggles.askPhone && phone.trim()) values.phone = phone.trim();
    onSubmit(text.trim(), values);
    setText('');
  }

  return (
    <div className="relative flex grow flex-col gap-3 overflow-y-auto px-4 py-4">
      <div className="max-w-[85%] rounded-2xl rounded-bl-sm bg-muted px-3.5 py-2 text-sm text-foreground shadow-xs">
        <MessageText text={greeting} />
      </div>

      <div className="flex flex-col gap-2.5">
        {toggles.askName && (
          <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
            Name
            <Input value={name} onChange={(e) => setName(e.target.value)} data-testid="webchat-prechat-name" />
          </label>
        )}
        {toggles.askEmail && (
          <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
            Email
            <Input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              data-testid="webchat-prechat-email"
            />
          </label>
        )}
        {toggles.askPhone && (
          <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
            Phone
            <Input
              type="tel"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              data-testid="webchat-prechat-phone"
            />
          </label>
        )}
      </div>

      <div className="mt-auto flex flex-col gap-2">
        {error && (
          <p className="text-xs text-destructive" data-testid="webchat-prechat-error">
            {error}
          </p>
        )}
        <Textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={2}
          className="resize-none"
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
          data-testid="webchat-prechat-message"
        />
        <Button type="button" onClick={submit} disabled={!canSend} data-testid="webchat-prechat-send">
          Send
        </Button>
      </div>

      {/* Off-screen honeypot - a real visitor never fills it (form-engine precedent). */}
      <div aria-hidden="true" className="absolute -left-[9999px] top-0 h-0 w-0 overflow-hidden">
        <label>
          Company
          <input
            type="text"
            tabIndex={-1}
            autoComplete="off"
            value={honeypot}
            onChange={(e) => onHoneypotChange(e.target.value)}
          />
        </label>
      </div>
    </div>
  );
}
