'use client';

/**
 * Tabs the Foundryx UIUX way (playbook 0.71.0 "Toggles > Tabs inside a card
 * are toggles too"): the tab strip is a segmented toggle whose thumb slides
 * from the old tab to the new one, and the new content fades in. A long strip
 * still scrolls sideways inside itself. `TabsList`, `TabsTrigger` and
 * `TabsContent` render these while the switch is on, with the same props;
 * which tab content stays mounted is unchanged (the workflow stays).
 */
import * as React from 'react';
import { Tabs as TabsPrimitive } from 'radix-ui';
import { cn } from '@/lib/utils';
import { PRESSED_CLASS } from '@/components/ui/primitive-classes';
import { SegmentThumb, useSegmentThumb } from './segment-thumb';

type Size = 'lg' | 'md' | 'sm' | 'xs';
const FxTabsSize = React.createContext<Size>('md');

const TRIGGER_SIZE: Record<Size, string> = {
  lg: 'h-9 px-4 text-sm gap-2 [&_svg]:size-4',
  md: 'h-7.5 px-3 text-sm gap-2 [&_svg]:size-4',
  sm: 'h-7 px-2.5 text-xs gap-1.5 [&_svg]:size-3.5',
  xs: 'h-6 px-2 text-xs gap-1 [&_svg]:size-3.5',
};

export function FxTabsList({
  className,
  size,
  ref: callerRef,
  // eslint-disable-next-line @typescript-eslint/no-unused-vars -- one fx look for every strip
  variant,
  // eslint-disable-next-line @typescript-eslint/no-unused-vars -- one fx look for every strip
  shape,
  ...props
}: React.ComponentProps<typeof TabsPrimitive.List> & {
  variant?: 'default' | 'button' | 'line' | null;
  shape?: 'default' | 'pill' | null;
  size?: Size | null;
}) {
  const listRef = React.useRef<HTMLDivElement | null>(null);
  const { place, animate } = useSegmentThumb(listRef, '[data-slot=tabs-trigger][data-state=active]');
  const mergedRef = React.useCallback(
    (node: HTMLDivElement | null) => {
      listRef.current = node;
      if (typeof callerRef === 'function') callerRef(node);
      else if (callerRef) (callerRef as React.RefObject<HTMLDivElement | null>).current = node;
    },
    [callerRef],
  );
  return (
    <FxTabsSize.Provider value={size ?? 'md'}>
      <div className="min-w-0 max-w-full">
        <TabsPrimitive.List
          data-slot="tabs-list"
          data-fx-tabs=""
          className={cn(
            'relative isolate inline-flex max-w-full min-w-0 shrink-0 items-center gap-0.5 overflow-x-auto rounded-(--fx-r-m) bg-(--fx-surface-2) p-0.5 ring-1 ring-inset ring-(--fx-line)',
            '[scrollbar-width:none] [&::-webkit-scrollbar]:hidden',
            className,
          )}
          {...props}
          ref={mergedRef}
        >
          <SegmentThumb place={place} animate={animate} />
          {props.children}
        </TabsPrimitive.List>
      </div>
    </FxTabsSize.Provider>
  );
}

export function FxTabsTrigger({ className, ...props }: React.ComponentProps<typeof TabsPrimitive.Trigger>) {
  const size = React.useContext(FxTabsSize);
  return (
    <TabsPrimitive.Trigger
      data-slot="tabs-trigger"
      className={cn(
        PRESSED_CLASS,
        'relative inline-flex shrink-0 cursor-pointer items-center justify-center whitespace-nowrap rounded-(--fx-r-s) font-medium text-(--fx-ink-2)',
        'hover:text-(--fx-ink) data-[state=active]:text-(--fx-ink) disabled:pointer-events-none disabled:opacity-50 data-disabled:pointer-events-none data-disabled:opacity-50',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-(--fx-link) focus-visible:ring-offset-0',
        '[&_svg]:shrink-0 [&_svg]:text-(--fx-ink-3) data-[state=active]:[&_svg]:text-(--fx-link)',
        TRIGGER_SIZE[size],
        className,
      )}
      {...props}
    />
  );
}

export function FxTabsContent({
  className,
  // eslint-disable-next-line @typescript-eslint/no-unused-vars -- one fx look
  variant,
  ...props
}: React.ComponentProps<typeof TabsPrimitive.Content> & { variant?: 'default' | null }) {
  return (
    <TabsPrimitive.Content
      data-slot="tabs-content"
      className={cn(
        'mt-2.5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-(--fx-link) data-[state=active]:animate-in data-[state=active]:fade-in-0 data-[state=active]:duration-(--fx-t-open)',
        className,
      )}
      {...props}
    />
  );
}
