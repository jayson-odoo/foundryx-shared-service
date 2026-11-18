'use client';

/**
 * The Foundryx UIUX on/off switch (playbook 0.71.0 "On/off switches"): the
 * track fills in the link colour when on, and the thumb slides across (0.4 s).
 * `Switch` renders it while the switch is on, with the same props.
 */
import * as React from 'react';
import { Switch as SwitchPrimitive } from 'radix-ui';
import { cn } from '@/lib/utils';
import { COARSE_HIT_TARGET_CLASS, PRESSED_CLASS } from '@/components/ui/primitive-classes';

const TRACK = {
  sm: 'h-5 w-8',
  md: 'h-6 w-10',
  lg: 'h-8 w-14',
  xl: 'h-9 w-16',
} as const;

/** How far the thumb travels: the track's width less its height. */
const TRAVEL = {
  sm: 'data-[state=checked]:translate-x-3 rtl:data-[state=checked]:-translate-x-3',
  md: 'data-[state=checked]:translate-x-4 rtl:data-[state=checked]:-translate-x-4',
  lg: 'data-[state=checked]:translate-x-6 rtl:data-[state=checked]:-translate-x-6',
  xl: 'data-[state=checked]:translate-x-7 rtl:data-[state=checked]:-translate-x-7',
} as const;

export function FxSwitch({
  className,
  thumbClassName,
  size,
  // eslint-disable-next-line @typescript-eslint/no-unused-vars -- one fx shape
  shape,
  // eslint-disable-next-line @typescript-eslint/no-unused-vars -- one fx look
  permanent,
  ...props
}: React.ComponentProps<typeof SwitchPrimitive.Root> & {
  thumbClassName?: string;
  size?: keyof typeof TRACK | null;
  shape?: 'pill' | 'square' | null;
  permanent?: boolean | null;
}) {
  return (
    <SwitchPrimitive.Root
      data-slot="switch"
      data-fx-switch=""
      className={cn(
        PRESSED_CLASS,
        COARSE_HIT_TARGET_CLASS,
        'peer inline-flex shrink-0 cursor-pointer items-center rounded-(--fx-r-pill) p-0.5',
        'bg-(--fx-line-2) data-[state=checked]:bg-(--fx-link)',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-(--fx-link) focus-visible:ring-offset-2 focus-visible:ring-offset-(--fx-surface)',
        'disabled:cursor-not-allowed disabled:opacity-50 aria-invalid:ring-2 aria-invalid:ring-(--fx-act)/40',
        TRACK[size ?? 'md'],
        className,
      )}
      {...props}
    >
      <SwitchPrimitive.Thumb
        data-fx-switch-thumb=""
        className={cn(
          'pointer-events-none block aspect-square h-full rounded-full bg-white shadow-[0_1px_3px_var(--fx-lift)]',
          'transition-[translate] duration-(--fx-t-toggle) ease-(--fx-ease-out)',
          TRAVEL[size ?? 'md'],
          thumbClassName,
        )}
      />
    </SwitchPrimitive.Root>
  );
}
