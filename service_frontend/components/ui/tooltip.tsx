'use client';

import * as React from 'react';
import { cn } from '@/lib/utils';
import { cva, type VariantProps } from 'class-variance-authority';
import { Tooltip as TooltipPrimitive } from 'radix-ui';
import { useFx } from '@/hooks/use-fx';

function TooltipProvider({ ...props }: React.ComponentProps<typeof TooltipPrimitive.Provider>) {
  return <TooltipPrimitive.Provider data-slot="tooltip-provider" {...props} />;
}

// A bare Root (AC-DLA-16): the ONE provider lives in
// `providers/tooltips-provider.tsx`, mounted once for the whole app. A
// per-Tooltip provider would each carry its own 0ms `delayDuration` default
// and race the app-wide 700ms one.
function Tooltip({ ...props }: React.ComponentProps<typeof TooltipPrimitive.Root>) {
  return <TooltipPrimitive.Root data-slot="tooltip" {...props} />;
}

function TooltipTrigger({ ...props }: React.ComponentProps<typeof TooltipPrimitive.Trigger>) {
  return <TooltipPrimitive.Trigger data-slot="tooltip-trigger" {...props} />;
}

const tooltipVariants = cva(
  // Opacity only (AC-DLA-16) - no scale/slide keyframes, at --duration-fast.
  'z-(--z-modal) overflow-hidden rounded-md px-3 py-1.5 text-xs duration-(--duration-fast) animate-in fade-in-0 data-[state=closed]:animate-out data-[state=closed]:fade-out-0',
  {
    variants: {
      variant: {
        light: 'border border-border bg-background text-foreground shadow-md shadow-black/5',
        dark: 'dark:border dark:border-border bg-zinc-950 text-white dark:bg-zinc-300 dark:text-black shadow-md shadow-black/5',
      },
    },
    defaultVariants: {
      variant: 'dark',
    },
  },
);

type TooltipContentProps = React.ComponentProps<typeof TooltipPrimitive.Content> &
  VariantProps<typeof tooltipVariants>;

// Foundryx UIUX switch (playbook-uiux.md): with it on, every existing tooltip
// takes the playbook look (solid themed backing, hairline edge, grow from 60%
// with a fade at the tooltip fade-in setting). Off renders the legacy body.
function TooltipContent(props: TooltipContentProps) {
  return useFx() ? <FxTooltipContent {...props} /> : <TooltipContentLegacy {...props} />;
}

function FxTooltipContent({ className, sideOffset = 6, variant, ...props }: TooltipContentProps) {
  // One look under the switch: the light/dark variants do not apply.
  void variant;
  return (
    <TooltipPrimitive.Content
      data-slot="tooltip-content"
      sideOffset={sideOffset}
      className={cn(
        'z-(--fx-z-tip) w-max max-w-[300px] rounded-(--fx-r-m) border border-(--fx-line) bg-[color-mix(in_srgb,var(--fx-surface)_var(--fx-tip-bg,92%),transparent)] px-2.5 py-1.5 text-sm text-(--fx-ink) shadow-[0_8px_24px_var(--fx-shade)] backdrop-blur-[6px] duration-(--fx-tip-fade,0.15s) ease-(--fx-ease-spring) animate-in fade-in-0 zoom-in-60 data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=closed]:zoom-out-60 motion-reduce:zoom-in-100 motion-reduce:zoom-out-100',
        className,
      )}
      {...props}
    />
  );
}

function TooltipContentLegacy({
  className,
  sideOffset = 4,
  variant,
  ...props
}: TooltipContentProps) {
  return (
    <TooltipPrimitive.Content
      data-slot="tooltip-content"
      sideOffset={sideOffset}
      className={cn(tooltipVariants({ variant }), className)}
      {...props}
    />
  );
}

export { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger };
