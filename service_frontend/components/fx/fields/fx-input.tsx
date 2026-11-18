'use client';

/**
 * The Foundryx UIUX text field and text area (playbook 0.71.0 "Fields":
 * Hover, Never browser up/down arrows, Notes that grow, Messages under a
 * field). `Input` and `Textarea` in `components/ui` render these while the
 * switch is on, with the same props, so every page gets them unchanged.
 */
import * as React from 'react';
import { cn } from '@/lib/utils';
import { FX_FIELD, FX_FIELD_SIZE, type FxFieldSize } from './classes';

export type FxInputProps = React.ComponentProps<'input'> & {
  variant?: FxFieldSize | null;
};

/**
 * Scrolling the page must never change a value: a focused number field
 * lets go of focus when the wheel turns over it, so the browser cannot step
 * it. The arrows themselves are hidden by the switch's global CSS.
 */
function stopWheelStep(event: React.WheelEvent<HTMLInputElement>) {
  if (event.currentTarget === document.activeElement) event.currentTarget.blur();
}

export function FxInput({ className, type, variant, onWheel, ...props }: FxInputProps) {
  return (
    <input
      data-slot="input"
      data-fx-field=""
      type={type}
      onWheel={
        type === 'number'
          ? (event) => {
              stopWheelStep(event);
              onWheel?.(event);
            }
          : onWheel
      }
      className={cn(
        'flex w-full',
        FX_FIELD,
        FX_FIELD_SIZE[variant ?? 'md'],
        type === 'number' && 'tabular-nums',
        'file:h-full file:border-0 file:bg-transparent file:p-0 file:font-medium file:text-(--fx-ink) [&[type=file]]:py-0',
        className,
      )}
      {...props}
    />
  );
}

export type FxTextareaProps = React.ComponentProps<'textarea'> & {
  variant?: FxFieldSize | null;
};

const TEXTAREA_SIZE: Record<FxFieldSize, string> = {
  sm: 'px-2.5 py-2.5 text-xs pointer-coarse:text-base',
  md: 'px-3 py-3 text-[0.8125rem] leading-(--text-sm--line-height) pointer-coarse:text-base',
  lg: 'px-4 py-4 text-sm pointer-coarse:text-base',
};

export function FxTextarea({ className, variant, ...props }: FxTextareaProps) {
  return (
    <textarea
      data-slot="textarea"
      data-fx-field=""
      className={cn('w-full', FX_FIELD, TEXTAREA_SIZE[variant ?? 'md'], className)}
      {...props}
    />
  );
}

/**
 * A note or remark that starts one line tall and grows a line at a time up
 * to 8 lines, then scrolls inside; it shrinks back the same way. Built on the
 * browser's content sizing, so typing, pasting and autofill work as normal.
 */
export function FxNoteField({ className, rows = 1, ...props }: FxTextareaProps) {
  return (
    <FxTextarea
      rows={rows}
      className={cn(
        'field-sizing-content min-h-[calc(1lh+1.5rem)] max-h-[calc(8lh+1.5rem)] resize-none overflow-y-auto py-2',
        className,
      )}
      {...props}
    />
  );
}

export interface FxFieldMessageProps {
  /** The message; nothing renders without one. */
  children?: React.ReactNode;
  /** `error` for a form error, `why` for the reason an action can't go ahead. */
  tone?: 'error' | 'why';
  id?: string;
  className?: string;
}

/**
 * A message under a field or button that never moves anything: it hangs
 * below its element without taking layout space, so the element and
 * everything beside it stay where they were. Put it inside a `relative`
 * wrapper together with the field (`FxField` does that).
 */
export function FxFieldMessage({ children, tone = 'error', id, className }: FxFieldMessageProps) {
  if (!children) return null;
  return (
    <p
      id={id}
      role={tone === 'error' ? 'alert' : undefined}
      data-fx-message={tone}
      className={cn(
        'pointer-events-none absolute start-0 top-full mt-1 text-xs leading-tight',
        tone === 'error' ? 'text-(--fx-act)' : 'text-(--fx-ink-2)',
        className,
      )}
    >
      {children}
    </p>
  );
}

/** A field and its message, positioned so the message never moves layout. */
export function FxField({
  message,
  tone,
  messageId,
  className,
  children,
}: {
  message?: React.ReactNode;
  tone?: 'error' | 'why';
  messageId?: string;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <div className={cn('relative', className)}>
      {children}
      <FxFieldMessage id={messageId} tone={tone}>
        {message}
      </FxFieldMessage>
    </div>
  );
}
