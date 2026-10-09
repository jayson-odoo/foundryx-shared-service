'use client';

import { useState } from 'react';
import { Send } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';

export interface ComposerProps {
  onSend: (text: string) => void;
  sending: boolean;
  error: string | null;
  honeypot: string;
  onHoneypotChange: (value: string) => void;
}

/**
 * The visitor's own composer (distinct from the admin inbox composer -
 * D-A7B-20, no attach control anywhere on this surface, uploads are OFF in
 * v1). A honeypot field travels alongside every send (D-A7B-22/AC-WEB-32);
 * a real visitor's browser never fills it in.
 */
export function Composer({ onSend, sending, error, honeypot, onHoneypotChange }: ComposerProps) {
  const [text, setText] = useState('');
  const canSend = text.trim().length > 0 && !sending;

  function submit() {
    if (!canSend) return;
    onSend(text.trim());
    setText('');
  }

  return (
    <div className="relative shrink-0 border-t border-border bg-background px-3 py-2.5">
      {error && (
        <p className="mb-1.5 text-xs text-destructive" data-testid="webchat-send-error">
          {error}
        </p>
      )}
      <div className="flex items-end gap-2">
        <Textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={1}
          className="max-h-24 min-h-9 resize-none"
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
          data-testid="webchat-composer-input"
        />
        <Button
          type="button"
          size="icon"
          onClick={submit}
          disabled={!canSend}
          aria-label="Send message"
          data-testid="webchat-composer-send"
        >
          <Send className="size-4" />
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
