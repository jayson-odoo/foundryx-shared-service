'use client';

/**
 * The Foundryx UIUX segmented toggle (playbook 0.71.0 "Toggles"): a thumb
 * slides between the options. Clicking anywhere on a two-option toggle flips
 * it; on a toggle with more options, clicking the chosen one moves to the
 * next. `ToggleGroup` / `ToggleGroupItem` render these while the switch is on,
 * with the same props. A `type="multiple"` group keeps its pressed buttons
 * (no thumb: several can be on).
 */
import * as React from 'react';
import { ToggleGroup as ToggleGroupPrimitive } from 'radix-ui';
import { cn } from '@/lib/utils';
import { PRESSED_CLASS } from '@/components/ui/primitive-classes';
import { SegmentThumb, useSegmentThumb } from './segment-thumb';

type RootProps = React.ComponentProps<typeof ToggleGroupPrimitive.Root> & {
  variant?: 'default' | 'outline' | null;
  size?: 'sm' | 'md' | 'lg' | null;
};

const FxToggleSize = React.createContext<'sm' | 'md' | 'lg'>('md');

const ROW =
  'relative isolate inline-flex items-center gap-0.5 rounded-(--fx-r-m) bg-(--fx-surface-2) p-0.5 ring-1 ring-inset ring-(--fx-line)';

/** The value after `current` in DOM order (wrapping), for a click on the chosen option. */
export function nextSegmentValue(values: string[], current: string): string {
  if (!values.length) return current;
  const at = values.indexOf(current);
  return values[(at + 1) % values.length];
}

function FxSingleToggleGroup({
  className,
  children,
  size,
  value,
  defaultValue,
  onValueChange,
  // eslint-disable-next-line @typescript-eslint/no-unused-vars -- always single here
  type,
  ...props
}: Omit<Extract<RootProps, { type: 'single' }>, 'variant'>) {
  const rootRef = React.useRef<HTMLDivElement>(null);
  const [inner, setInner] = React.useState(defaultValue ?? '');
  const current = value ?? inner;
  const { place, animate } = useSegmentThumb(rootRef, '[data-slot=toggle-group-item][data-state=on]');

  const change = (next: string) => {
    let chosen = next;
    if (!next) {
      // Radix clears a single group when the chosen option is clicked again;
      // the playbook moves to the next option instead.
      const values = Array.from(
        rootRef.current?.querySelectorAll<HTMLElement>('[data-slot=toggle-group-item]:not([data-disabled])') ?? [],
      ).map((el) => el.dataset.value ?? '');
      chosen = nextSegmentValue(values, current);
      if (chosen === current) return;
    }
    if (value === undefined) setInner(chosen);
    onValueChange?.(chosen);
  };

  return (
    <ToggleGroupPrimitive.Root
      ref={rootRef}
      data-slot="toggle-group"
      data-fx-toggle="single"
      type="single"
      value={current}
      onValueChange={change}
      className={cn(ROW, className)}
      {...props}
    >
      <SegmentThumb place={place} animate={animate} />
      <FxToggleSize.Provider value={size ?? 'md'}>{children}</FxToggleSize.Provider>
    </ToggleGroupPrimitive.Root>
  );
}

export function FxToggleGroup(props: RootProps) {
  if (props.type === 'single') {
    // eslint-disable-next-line @typescript-eslint/no-unused-vars -- the fx look has one variant
    const { variant, ...single } = props;
    return <FxSingleToggleGroup {...single} />;
  }
  // eslint-disable-next-line @typescript-eslint/no-unused-vars -- the fx look has one variant
  const { className, children, size, variant, ...multiple } = props;
  return (
    <ToggleGroupPrimitive.Root
      data-slot="toggle-group"
      data-fx-toggle="multiple"
      className={cn(ROW, className)}
      {...multiple}
    >
      <FxToggleSize.Provider value={size ?? 'md'}>{children}</FxToggleSize.Provider>
    </ToggleGroupPrimitive.Root>
  );
}

const ITEM_SIZE = {
  sm: 'h-6 px-2 text-xs',
  md: 'h-7.5 px-3 text-[0.8125rem]',
  lg: 'h-9 px-3.5 text-sm',
} as const;

export function FxToggleGroupItem({
  className,
  children,
  size,
  // eslint-disable-next-line @typescript-eslint/no-unused-vars -- the fx look has one variant
  variant,
  ...props
}: React.ComponentProps<typeof ToggleGroupPrimitive.Item> & {
  variant?: 'default' | 'outline' | null;
  size?: 'sm' | 'md' | 'lg' | null;
}) {
  const groupSize = React.useContext(FxToggleSize);
  return (
    <ToggleGroupPrimitive.Item
      data-slot="toggle-group-item"
      data-value={props.value}
      className={cn(
        PRESSED_CLASS,
        'relative inline-flex shrink-0 cursor-pointer items-center justify-center gap-1 rounded-(--fx-r-s) font-medium text-(--fx-ink-2)',
        'hover:text-(--fx-ink) data-[state=on]:text-(--fx-ink) disabled:pointer-events-none disabled:opacity-50',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-(--fx-link)',
        '[&_svg]:size-4 [&_svg]:shrink-0',
        // A multiple-choice group has no thumb: its pressed buttons fill instead.
        '[[data-fx-toggle=multiple]_&]:data-[state=on]:bg-(--fx-surface) [[data-fx-toggle=multiple]_&]:data-[state=on]:shadow-[0_1px_3px_var(--fx-lift)]',
        ITEM_SIZE[size ?? groupSize],
        className,
      )}
      {...props}
    >
      {children}
    </ToggleGroupPrimitive.Item>
  );
}
