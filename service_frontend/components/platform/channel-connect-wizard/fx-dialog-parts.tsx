'use client';

/**
 * Small Foundryx UIUX dialog pieces the channels slice shares (connect
 * wizard, Replace token, the secret dialogs): the playbook surface, a footer
 * with the safe button first and the dialog's one action in red, and the
 * line under that action for a result or a reason.
 */
import type { ReactNode } from 'react';
import { Loader2 } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { useHideMainAction } from '@/components/fx/actions/page-actions-context';

export const FX_DIALOG_CLASS =
  'w-full max-w-[460px] gap-4 rounded-(--fx-r-l) border-(--fx-line) bg-(--fx-surface) p-6 text-(--fx-ink) max-sm:w-[calc(100%-32px)]';

export const FX_DIALOG_TITLE_CLASS = 'text-lg font-bold text-(--fx-ink)';

export const FX_LABEL_CLASS = 'text-sm font-semibold text-(--fx-ink-2)';

/** While a dialog is open its own action is the page's one red action. */
export function FxHideMainWhile({ open }: { open: boolean }) {
  useHideMainAction(open);
  return null;
}

export interface FxDialogFooterProps {
  /** The safe button ("Cancel", "Back"), named for what it does. */
  safe?: { label: string; onClick: () => void; disabled?: boolean };
  /** The dialog's one action, verb + object. */
  action?: {
    label: string;
    onClick: () => void;
    disabled?: boolean;
    working?: boolean;
    icon?: ReactNode;
  };
  /** The line under the action: a reason or a result (`tone`). */
  note?: { text: string; tone: 'why' | 'quiet' | 'ok' } | null;
}

export function FxDialogFooter({ safe, action, note }: FxDialogFooterProps) {
  return (
    <div className="mt-2 flex flex-col items-end gap-1">
      <div className="flex flex-wrap items-center justify-end gap-2">
        {safe && (
          <Button
            type="button"
            variant="fx-quiet"
            className="h-auto min-h-11 rounded-(--fx-r-pill) px-5"
            onClick={safe.onClick}
            disabled={safe.disabled}
          >
            {safe.label}
          </Button>
        )}
        {action && (
          <Button
            type="button"
            variant="fx-main"
            className="h-auto min-h-11 px-5"
            aria-disabled={action.disabled || action.working ? true : undefined}
            onClick={() => {
              if (!action.disabled && !action.working) action.onClick();
            }}
          >
            {action.working ? <Loader2 aria-hidden="true" className="size-4 animate-spin" /> : action.icon}
            {action.label}
          </Button>
        )}
      </div>
      {note && <FxNote tone={note.tone}>{note.text}</FxNote>}
    </div>
  );
}

/** A one-line result or reason beside an action. */
export function FxNote({
  tone,
  children,
  className,
}: {
  tone: 'why' | 'quiet' | 'ok';
  children: ReactNode;
  className?: string;
}) {
  return (
    <p
      role={tone === 'why' ? 'alert' : 'status'}
      className={cn(
        'max-w-80 text-end text-sm',
        tone === 'why' && 'font-semibold text-[color-mix(in_srgb,var(--fx-act)_82%,var(--fx-surface))]',
        tone === 'quiet' && 'text-(--fx-ink-2)',
        tone === 'ok' && 'text-(--fx-ok-ink)',
        className,
      )}
    >
      {children}
    </p>
  );
}
