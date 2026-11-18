'use client';

/**
 * The Foundryx UIUX look for the few screens still on the bare `Select`
 * (playbook 0.71.0 "Dropdowns"): the closed field looks like every other
 * field with a grey chevron, and the list is styled like the menus, the
 * chosen row bold with a tick. `components/ui/select.tsx` renders these parts
 * while the switch is on.
 */
import * as React from 'react';
import { Check, ChevronDown } from 'lucide-react';
import { Select as SelectPrimitive } from 'radix-ui';
import { cn } from '@/lib/utils';
import { FX_FIELD, FX_MENU, FX_MENU_ROW } from './classes';
import { fxControlName, useFxFieldIds } from './fx-field-context';

const TRIGGER_SIZE = {
  sm: 'h-7 px-2.5 text-xs',
  md: 'h-8.5 px-3 text-[0.8125rem]',
  lg: 'h-10 px-4 text-sm',
} as const;

export function FxSelectTrigger({
  className,
  children,
  size,
  ...props
}: React.ComponentProps<typeof SelectPrimitive.Trigger> & { size?: keyof typeof TRIGGER_SIZE | null }) {
  // Inside a labelled FxField the trigger takes the field's id and label.
  const field = useFxFieldIds();
  const naming = field
    ? fxControlName(
        {
          id: props.id,
          ariaLabel: props['aria-label'],
          ariaLabelledBy: props['aria-labelledby'],
          ariaDescribedBy: props['aria-describedby'],
        },
        field,
      )
    : null;
  return (
    <SelectPrimitive.Trigger
      data-slot="select-trigger"
      data-fx-field=""
      className={cn(
        FX_FIELD,
        'flex w-full items-center justify-between gap-1 pointer-coarse:text-base data-placeholder:text-(--fx-ink-3) [&>span]:line-clamp-1',
        TRIGGER_SIZE[size ?? 'md'],
        className,
      )}
      {...props}
      {...naming}
    >
      {children}
      <SelectPrimitive.Icon asChild>
        <ChevronDown className="size-4 shrink-0 text-(--fx-ink-3)" />
      </SelectPrimitive.Icon>
    </SelectPrimitive.Trigger>
  );
}

export function FxSelectContent({
  className,
  children,
  position = 'popper',
  ...props
}: React.ComponentProps<typeof SelectPrimitive.Content>) {
  return (
    <SelectPrimitive.Portal>
      <SelectPrimitive.Content
        data-slot="select-content"
        position={position}
        className={cn(
          'relative z-(--z-modal) max-h-96 min-w-[8rem] overflow-hidden',
          FX_MENU,
          position === 'popper' && 'data-[side=bottom]:translate-y-1 data-[side=top]:-translate-y-1',
          className,
        )}
        {...props}
      >
        <SelectPrimitive.Viewport
          className={cn(
            'p-1',
            position === 'popper' &&
              'h-[var(--radix-select-trigger-height)] w-full min-w-[var(--radix-select-trigger-width)]',
          )}
        >
          {children}
        </SelectPrimitive.Viewport>
      </SelectPrimitive.Content>
    </SelectPrimitive.Portal>
  );
}

export function FxSelectItem({
  className,
  children,
  ...props
}: React.ComponentProps<typeof SelectPrimitive.Item>) {
  return (
    <SelectPrimitive.Item
      data-slot="select-item"
      className={cn(FX_MENU_ROW, 'relative ps-8 data-[state=checked]:font-semibold', className)}
      {...props}
    >
      <span className="absolute start-2 flex size-4 items-center justify-center">
        <SelectPrimitive.ItemIndicator>
          <Check className="size-4 text-(--fx-link)" />
        </SelectPrimitive.ItemIndicator>
      </span>
      <SelectPrimitive.ItemText>{children}</SelectPrimitive.ItemText>
    </SelectPrimitive.Item>
  );
}
