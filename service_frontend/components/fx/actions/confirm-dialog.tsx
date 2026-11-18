'use client';

/**
 * Confirm before what can't be undone (playbook 0.71.0 "Actions"), as SS
 * applies it (answers Q2 and the gap-audit choices in playbook-uiux.md).
 *
 * - The title is the question with its object; one line says what happens and
 *   what does not come back. Never "Are you sure?".
 * - Bottom right: the safe choice on the left, named for what it keeps; the
 *   action on the right as verb + object, red when it destroys something.
 * - Focus starts on the safe button; Esc and clicking outside choose it.
 * - The action needs a 3 s press and hold (settings "Press and hold to
 *   confirm" and "Hold time"): a red line runs clockwise round the button and
 *   a countdown counts 3.0 to 0.0; letting go or moving more than 10px
 *   cancels.
 * - Typed variant (SS's few that wipe a lot): type the record's name or
 *   number; that replaces the hold, and the action stays greyed with "Type
 *   the name to confirm." until it matches (case and spaces ignored).
 * - While open, the page header's red action hides ("Never twice").
 *
 * Rendered only while the Foundryx UIUX switch is on. Which actions ask first
 * never changes here: that is the workflow.
 */
import {
  useEffect,
  useId,
  useRef,
  useState,
  type KeyboardEvent,
  type PointerEvent,
} from 'react';
import { cn } from '@/lib/utils';
import { useFxSetting } from '@/hooks/use-fx';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from '@/components/ui/dialog';
import { useHideMainAction } from './page-actions-context';

export const FX_HOLD_TIP = (seconds: number) =>
  `Press and hold for ${seconds} seconds`;

const TICK_MS = 50;
const MOVE_CANCEL_PX = 10;

/** Typed confirmation matches ignoring case and spaces. */
export function fxTypedMatches(typed: string, expected: string): boolean {
  const norm = (value: string) => value.toLowerCase().replace(/\s+/g, '');
  return norm(expected) !== '' && norm(typed) === norm(expected);
}

interface FxHoldButtonProps {
  label: string;
  holdMs: number;
  destructive?: boolean;
  onConfirm: () => void;
  onHoldStart?: () => void;
}

/** The press-and-hold action button with its ring and countdown. */
export function FxHoldButton({
  label,
  holdMs,
  destructive,
  onConfirm,
  onHoldStart,
}: FxHoldButtonProps) {
  const tipId = useId();
  const [progress, setProgress] = useState<number | null>(null);
  const [backing, setBacking] = useState(false);
  const hold = useRef<{
    t0: number;
    x: number | null;
    y: number | null;
    tick: ReturnType<typeof setInterval>;
  } | null>(null);
  const seconds = holdMs / 1000;

  const stop = (done = false) => {
    const current = hold.current;
    if (!current) return;
    clearInterval(current.tick);
    hold.current = null;
    if (done) return;
    setBacking(true);
    setProgress(null);
  };

  const start = (x: number | null, y: number | null) => {
    if (hold.current) return;
    setBacking(false);
    setProgress(0);
    onHoldStart?.();
    const t0 = Date.now();
    hold.current = {
      t0,
      x,
      y,
      tick: setInterval(() => {
        const p = Math.min(1, (Date.now() - t0) / holdMs);
        setProgress(p);
        if (p >= 1) {
          stop(true);
          onConfirm();
        }
      }, TICK_MS),
    };
  };

  useEffect(() => () => stop(true), []);

  const left = progress === null ? null : (seconds * (1 - progress)).toFixed(1);

  return (
    <>
      <Button
        type="button"
        variant={destructive ? 'fx-main' : 'fx-quiet'}
        title={FX_HOLD_TIP(seconds)}
        aria-describedby={tipId}
        data-fx-hold=""
        data-holding={progress !== null ? '' : undefined}
        className={cn(
          'relative h-auto min-h-11 touch-none select-none gap-1 rounded-(--fx-r-pill) px-5',
          !destructive && 'text-(--fx-ink)',
        )}
        onClick={(event) => event.preventDefault()}
        onContextMenu={(event) => event.preventDefault()}
        onPointerDown={(event: PointerEvent<HTMLButtonElement>) => {
          if (event.button !== 0) return;
          try {
            event.currentTarget.setPointerCapture(event.pointerId);
          } catch {
            // Synthetic events carry no capturable pointer.
          }
          start(event.clientX, event.clientY);
        }}
        onPointerMove={(event: PointerEvent<HTMLButtonElement>) => {
          const h = hold.current;
          if (
            h &&
            h.x !== null &&
            h.y !== null &&
            Math.hypot(event.clientX - h.x, event.clientY - h.y) >
              MOVE_CANCEL_PX
          )
            stop();
        }}
        onPointerUp={() => stop()}
        onPointerCancel={() => stop()}
        onBlur={() => stop()}
        onKeyDown={(event: KeyboardEvent<HTMLButtonElement>) => {
          if (event.key !== ' ' && event.key !== 'Enter') return;
          event.preventDefault();
          if (!event.repeat) start(null, null);
        }}
        onKeyUp={(event: KeyboardEvent<HTMLButtonElement>) => {
          if (event.key === ' ' || event.key === 'Enter') stop();
        }}
      >
        <span>{label}</span>
        <span
          aria-hidden="true"
          data-fx-countdown=""
          className={cn(
            'inline-block w-[3ch] text-end tabular-nums transition-opacity duration-(--fx-t-press)',
            left === null ? 'opacity-0' : 'opacity-100',
          )}
        >
          {left}
        </span>
        <svg
          aria-hidden="true"
          className="pointer-events-none absolute -inset-[5px] h-[calc(100%+10px)] w-[calc(100%+10px)] overflow-visible"
        >
          <rect
            x="1.5"
            y="1.5"
            pathLength={100}
            rx="25"
            className={cn(
              'h-[calc(100%-3px)] w-[calc(100%-3px)] fill-none stroke-(--fx-act) [stroke-dasharray:100_100] [stroke-linecap:round] [stroke-width:3]',
              backing
                ? 'transition-[stroke-dashoffset] duration-(--fx-t-open) ease-(--fx-ease-out)'
                : 'transition-[stroke-dashoffset] duration-(--fx-t-press) ease-linear',
            )}
            style={{ strokeDashoffset: 100 - (progress ?? 0) * 100 }}
          />
        </svg>
      </Button>
      <span id={tipId} className="sr-only">
        {FX_HOLD_TIP(seconds)}
      </span>
    </>
  );
}

export interface FxConfirmDialogProps {
  open: boolean;
  /** The question with its object: "Cancel QT-2026-014?" */
  title: string;
  /** What happens and what does not come back. */
  line?: string;
  /** The safe button, named for what it keeps: "Keep quotation". */
  keepLabel: string;
  /** Verb + object: "Cancel quotation". */
  actionLabel: string;
  destructive?: boolean;
  /** Typed confirmation: the record's name or number to type. */
  typed?: { expected: string };
  /** False for a single click (Discard changes). Default: the setting. */
  hold?: boolean;
  onKeep: () => void;
  onConfirm: () => void;
}

export function FxConfirmDialog({
  open,
  title,
  line,
  keepLabel,
  actionLabel,
  destructive,
  typed,
  hold,
  onKeep,
  onConfirm,
}: FxConfirmDialogProps) {
  const holdSetting = useFxSetting('hold') !== false;
  const holdMs = Number(useFxSetting('hold-time') ?? 3) * 1000;
  const [text, setText] = useState('');
  const [said, setSaid] = useState('');
  const keepRef = useRef<HTMLButtonElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const inputId = useId();
  const whyId = useId();
  useHideMainAction(open);

  useEffect(() => {
    if (!open) {
      setText('');
      setSaid('');
    }
  }, [open]);

  const needsHold = !typed && (hold ?? holdSetting);
  const matches = typed ? fxTypedMatches(text, typed.expected) : true;

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onKeep()}>
      <DialogContent
        role="alertdialog"
        showCloseButton={false}
        data-fx-confirm=""
        className="max-w-md gap-3 rounded-(--fx-r-l) border-(--fx-line) bg-(--fx-surface) p-6 text-(--fx-ink) max-sm:w-[calc(100%-32px)]"
        onOpenAutoFocus={(event) => {
          event.preventDefault();
          (typed ? inputRef.current : keepRef.current)?.focus();
        }}
      >
        <DialogTitle className="text-lg font-bold text-(--fx-ink)">
          {title}
        </DialogTitle>
        {line ? (
          <DialogDescription className="text-sm text-(--fx-ink-2)">
            {line}
          </DialogDescription>
        ) : (
          <DialogDescription className="sr-only">{title}</DialogDescription>
        )}
        {typed && (
          <div className="flex flex-col gap-1.5">
            <label
              htmlFor={inputId}
              className="text-sm font-semibold text-(--fx-ink-2)"
            >
              {`Type "${typed.expected}"`}
            </label>
            <input
              ref={inputRef}
              id={inputId}
              aria-label={`Type "${typed.expected}"`}
              value={text}
              autoComplete="off"
              spellCheck={false}
              onChange={(event) => setText(event.target.value)}
              className="min-h-10 rounded-(--fx-r-m) border border-(--fx-line-2) bg-(--fx-surface) px-3 text-base text-(--fx-ink) outline-none focus-visible:border-(--fx-link) focus-visible:shadow-[0_0_0_3px_var(--fx-link-bg)]"
            />
          </div>
        )}
        <div className="mt-2 flex flex-nowrap items-start justify-end gap-2">
          <Button
            ref={keepRef}
            type="button"
            variant="fx-quiet"
            className="h-auto min-h-11 rounded-(--fx-r-pill) px-5"
            onClick={onKeep}
          >
            {keepLabel}
          </Button>
          {needsHold ? (
            <FxHoldButton
              label={actionLabel}
              holdMs={holdMs}
              destructive={destructive}
              onHoldStart={() => setSaid('Hold to confirm')}
              onConfirm={onConfirm}
            />
          ) : (
            <div className="relative flex flex-col items-end">
              <Button
                type="button"
                variant={destructive ? 'fx-main' : 'fx-quiet'}
                aria-disabled={matches ? undefined : true}
                aria-describedby={matches ? undefined : whyId}
                className={cn(
                  'h-auto min-h-11 rounded-(--fx-r-pill) px-5',
                  !destructive && 'text-(--fx-ink)',
                  !matches && 'cursor-not-allowed opacity-45',
                )}
                onClick={() => {
                  if (matches) onConfirm();
                }}
              >
                {actionLabel}
              </Button>
              {!matches && (
                <p
                  id={whyId}
                  className="mt-1 text-end text-sm font-semibold text-[color-mix(in_srgb,var(--fx-act)_82%,var(--fx-surface))]"
                >
                  Type the name to confirm.
                </p>
              )}
            </div>
          )}
        </div>
        <span role="status" aria-live="polite" className="sr-only">
          {said}
        </span>
      </DialogContent>
    </Dialog>
  );
}

/** The dirty guard's question (single click, answers): "Discard changes to
 *  Lim Wei Jie?" with "Keep editing" and a red "Discard changes". */
export function FxDiscardDialog({
  open,
  name,
  onKeep,
  onDiscard,
}: {
  open: boolean;
  name?: string;
  onKeep: () => void;
  onDiscard: () => void;
}) {
  return (
    <FxConfirmDialog
      open={open}
      title={name ? `Discard changes to ${name}?` : 'Discard changes?'}
      line="Your edits are not saved and do not come back."
      keepLabel="Keep editing"
      actionLabel="Discard changes"
      destructive
      hold={false}
      onKeep={onKeep}
      onConfirm={onDiscard}
    />
  );
}
