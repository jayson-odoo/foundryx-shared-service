'use client';

/**
 * Secrets the Foundryx UIUX way (gap audit "Secrets shown once"; playbook
 * 0.71.0 "Password strength" for the eye):
 * - `FxSecretInput`: typing one in. A password field with an eye icon button
 *   inside it (`aria-pressed`, reachable by Tab). `SecretInput` renders it
 *   while the switch is on.
 * - `FxSecretOnce`: a new secret, shown in full only in the dialog that made
 *   it: read-only, monospace, a Copy icon button beside it, and one warning
 *   line under it.
 * - `FxSavedSecret`: a saved one comes back as "Saved · ending a91c" with
 *   Replace, never filled in.
 */
import { forwardRef, useEffect, useId, useRef, useState } from 'react';
import { Check, Copy, Eye, EyeOff } from 'lucide-react';
import { cn } from '@/lib/utils';
import { secretEnding } from '@/lib/fx/fields';
import { useCopyToClipboard } from '@/hooks/use-copy-to-clipboard';
import { Button } from '@/components/ui/button';
import { FX_FIELD, FX_FIELD_BOX } from './classes';
import { FxInput, type FxInputProps } from './fx-input';

/** How long the Copy button shows its tick (playbook Hold to Copy timing). */
export const FX_COPIED_MS = 1400;

export const FxSecretInput = forwardRef<HTMLInputElement, Omit<FxInputProps, 'type'>>(function FxSecretInput(
  { className, ...props },
  ref,
) {
  const [revealed, setRevealed] = useState(false);
  return (
    <div className="relative">
      <FxInput ref={ref} type={revealed ? 'text' : 'password'} className={cn('pe-10', className)} {...props} />
      <Button
        type="button"
        variant="ghost"
        mode="icon"
        size="sm"
        aria-label={revealed ? 'Hide value' : 'Show value'}
        aria-pressed={revealed}
        className="absolute end-1 top-1/2 -translate-y-1/2 text-(--fx-ink-3) hover:text-(--fx-ink)"
        onClick={() => setRevealed((s) => !s)}
      >
        {revealed ? <EyeOff aria-hidden="true" /> : <Eye aria-hidden="true" />}
      </Button>
    </div>
  );
});

export interface FxSecretOnceProps {
  /** The new secret, in full. Forget it when the dialog closes. */
  value: string;
  /** The field's accessible name ("API key", "Signing secret"). */
  label: string;
  className?: string;
}

export function FxSecretOnce({ value, label, className }: FxSecretOnceProps) {
  const { copyToClipboard, isCopied, error } = useCopyToClipboard({ timeout: FX_COPIED_MS });
  const inputRef = useRef<HTMLInputElement>(null);
  const noteId = useId();
  const copy = () => {
    copyToClipboard(value);
  };
  // A refused copy leaves the text selected, so the keyboard can copy it.
  useEffect(() => {
    if (!error || !inputRef.current) return;
    inputRef.current.focus();
    inputRef.current.select();
  }, [error]);
  return (
    <div className={cn('flex flex-col gap-1.5', className)}>
      <div className="flex items-center gap-2">
        <input
          ref={inputRef}
          readOnly
          value={value}
          aria-label={label}
          aria-describedby={noteId}
          onFocus={(e) => e.currentTarget.select()}
          className={cn(FX_FIELD, 'h-8.5 min-w-0 flex-1 px-3 font-mono text-[0.8125rem] pointer-coarse:text-base')}
        />
        <Button
          type="button"
          variant="outline"
          mode="icon"
          aria-label={isCopied ? 'Copied' : 'Copy'}
          onClick={copy}
          className="shrink-0"
        >
          {isCopied ? <Check aria-hidden="true" className="text-(--fx-ok)" /> : <Copy aria-hidden="true" />}
        </Button>
      </div>
      <p id={noteId} aria-live="polite" className="text-xs text-(--fx-warn-ink)">
        {error
          ? "Couldn't copy. It's selected, so press Ctrl+C."
          : isCopied
            ? 'Copied'
            : "Copy it now. It won't be shown again."}
      </p>
    </div>
  );
}

export function FxSavedSecret({
  ending,
  onReplace,
  className,
}: {
  /** The saved secret's last characters ("a91c"), from the server. */
  ending: string;
  onReplace: () => void;
  className?: string;
}) {
  return (
    <div className={cn(FX_FIELD_BOX, 'h-8.5 justify-between gap-2 ps-3 pe-1 text-[0.8125rem]', className)}>
      <span className="text-(--fx-ink-2)">
        Saved · <span className="font-mono">{secretEnding(ending)}</span>
      </span>
      <Button type="button" variant="ghost" size="sm" onClick={onReplace}>
        Replace
      </Button>
    </div>
  );
}
