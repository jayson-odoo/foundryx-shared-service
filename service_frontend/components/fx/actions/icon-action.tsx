'use client';

/**
 * An Other Action (playbook 0.71.0 "Other Actions are icon buttons").
 *
 * - Icon only; its label is the hover tooltip (press and hold on touch) and
 *   always its `aria-label`. Hover never grows it.
 * - Keyboard focus has no pointer, so focus slides the label out beside the
 *   icon (up to 240px) instead.
 * - The delete × turns red on hover with "Delete" as its tooltip.
 * - Greyed with its reason as the tooltip when it cannot apply.
 */
import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from 'react';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { FxTooltip } from '@/components/fx/fx-tooltip';
import { FxIcon, type FxAnyIconName } from '@/components/fx/icons';

export interface FxIconActionProps
  extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'children'> {
  label: string;
  icon: FxAnyIconName;
  /** Drawn instead of `icon` (an action that brings its own icon). */
  iconNode?: ReactNode;
  /** Greys the button; the reason becomes its tooltip. */
  disabledReason?: string;
  tone?: 'delete';
  /** 36px instead of 44px, for dense rows. */
  mini?: boolean;
}

export const FxIconActionButton = forwardRef<
  HTMLButtonElement,
  FxIconActionProps
>(function FxIconActionButton(
  { label, icon, iconNode, disabledReason, tone, mini, className, onClick, ...rest },
  ref,
) {
  const blocked = Boolean(disabledReason);
  return (
    <Button
      ref={ref}
      type="button"
      variant="fx-icon"
      aria-label={label}
      aria-disabled={blocked ? true : undefined}
      data-fx-tone={tone}
      className={cn(
        'group/ib h-auto rounded-(--fx-r-pill) gap-0 px-3 focus-visible:gap-1.5',
        mini ? 'min-h-9 min-w-9 px-2' : 'min-h-11 min-w-11',
        tone === 'delete' &&
          'hover:border-(--fx-act) hover:bg-(--fx-act) hover:text-(--fx-act-ink) focus-visible:border-(--fx-act) focus-visible:bg-(--fx-act) focus-visible:text-(--fx-act-ink)',
        className,
      )}
      onClick={(event) => {
        if (blocked) {
          event.preventDefault();
          return;
        }
        onClick?.(event);
      }}
      {...rest}
    >
      {iconNode ?? <FxIcon name={icon} size={18} />}
      <span
        aria-hidden="true"
        data-fx-decor=""
        className="max-w-0 overflow-hidden whitespace-nowrap opacity-0 transition-[max-width,opacity] duration-(--fx-t-hover) ease-(--fx-ease-out) group-focus-visible/ib:max-w-[240px] group-focus-visible/ib:opacity-100"
      >
        {label}
      </span>
    </Button>
  );
});

/** The icon action with its tooltip. */
export function FxIconAction(props: FxIconActionProps) {
  const tip = props.disabledReason ?? props.label;
  return (
    <FxTooltip label={tip}>
      <FxIconActionButton {...props} />
    </FxTooltip>
  );
}
