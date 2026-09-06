'use client';

import * as React from 'react';
import { cn } from '@/lib/utils';
import { Drawer as DrawerPrimitive } from 'vaul';
import { OVERLAY_CLASS_STATIC } from '@/components/ui/primitive-classes';

const Drawer = ({ shouldScaleBackground = true, ...props }: React.ComponentProps<typeof DrawerPrimitive.Root>) => (
  <DrawerPrimitive.Root shouldScaleBackground={shouldScaleBackground} {...props} />
);

function DrawerTrigger({ ...props }: React.ComponentProps<typeof DrawerPrimitive.Trigger>) {
  return <DrawerPrimitive.Trigger data-slot="drawer-trigger" {...props} />;
}

function DrawerPortal({ ...props }: React.ComponentProps<typeof DrawerPrimitive.Portal>) {
  return <DrawerPrimitive.Portal data-slot="drawer-portal" {...props} />;
}

function DrawerClose({ ...props }: React.ComponentProps<typeof DrawerPrimitive.Close>) {
  return <DrawerPrimitive.Close data-slot="drawer-close" {...props} />;
}

function DrawerOverlay({ className, ...props }: React.ComponentProps<typeof DrawerPrimitive.Overlay>) {
  return (
    <DrawerPrimitive.Overlay
      data-slot="drawer-overlay"
      className={cn(OVERLAY_CLASS_STATIC, className)}
      {...props}
    />
  );
}

// T3 fix round 1 finding 11 - the same `hasDialogTitleInChildren` fallback
// `DialogContent` has (dialog.tsx): a Radix `Content` with no `Title`
// descendant throws an accessibility warning (and screen readers announce
// nothing), and this repo's nav/mega-menu drawers (header.tsx) shipped with
// no `DrawerTitle` at all. A caller that DOES render one keeps it (this
// fallback stays sr-only and never displaces a real heading).
function hasDrawerTitleInChildren(children: React.ReactNode): boolean {
  const check = (nodes: React.ReactNode): boolean => {
    return React.Children.toArray(nodes).some((child) => {
      if (!React.isValidElement(child)) return false;
      if (child.type === DrawerTitle) return true;
      const grandChildren = (child.props as { children?: React.ReactNode })?.children;
      if (grandChildren !== undefined) return check(grandChildren);
      return false;
    });
  };
  return check(children);
}

function DrawerContent({ className, children, ...props }: React.ComponentProps<typeof DrawerPrimitive.Content>) {
  const needsFallbackTitle = !hasDrawerTitleInChildren(children);
  return (
    <DrawerPortal>
      <DrawerOverlay />
      <DrawerPrimitive.Content
        data-slot="drawer-content"
        // vaul drives its own drag-tracked, velocity-dismissed open/close
        // animation (AC-DLA-23) - it stamps `data-vaul-drawer-direction` on
        // this element itself, so every side's box shape lives here rather
        // than a `side` prop the way Sheet takes one.
        //
        // T3 fix round 1 finding 10: the left/right variants used to default
        // `w-3/4 sm:max-w-sm` - a data-ATTRIBUTE-scoped Tailwind utility,
        // which compiles to a two-selector rule
        // (`[data-vaul-drawer-direction=left].w-3\/4{...}`) and so
        // OUT-SPECIFIES a plain unmodified `w-[275px]` on the consumer's
        // `className` regardless of source order - `header.tsx`'s nav
        // drawer asked for 275px and silently got 75% of the viewport
        // instead. No default width here; the one drawer this repo ships
        // (`header.tsx`'s mobile nav) already sets its own width via
        // `className`, and a future left/right consumer that wants a
        // default should size itself explicitly too rather than rely on a
        // primitive default that can't be overridden without out-specifying
        // it back.
        className={cn(
          'group/drawer-content bg-background fixed z-(--z-modal) flex flex-col border',
          'data-[vaul-drawer-direction=bottom]:inset-x-0 data-[vaul-drawer-direction=bottom]:bottom-0 data-[vaul-drawer-direction=bottom]:mt-24 data-[vaul-drawer-direction=bottom]:max-h-[80vh] data-[vaul-drawer-direction=bottom]:rounded-t-[10px] data-[vaul-drawer-direction=bottom]:border-t',
          'data-[vaul-drawer-direction=top]:inset-x-0 data-[vaul-drawer-direction=top]:top-0 data-[vaul-drawer-direction=top]:mb-24 data-[vaul-drawer-direction=top]:max-h-[80vh] data-[vaul-drawer-direction=top]:rounded-b-[10px] data-[vaul-drawer-direction=top]:border-b',
          'data-[vaul-drawer-direction=left]:inset-y-0 data-[vaul-drawer-direction=left]:start-0 data-[vaul-drawer-direction=left]:h-full data-[vaul-drawer-direction=left]:border-e',
          'data-[vaul-drawer-direction=right]:inset-y-0 data-[vaul-drawer-direction=right]:end-0 data-[vaul-drawer-direction=right]:h-full data-[vaul-drawer-direction=right]:border-s',
          className,
        )}
        {...props}
      >
        {/* The pull handle only makes sense on a top/bottom sheet - a
            left/right nav drawer is dismissed by swiping the edge, not a
            handle. */}
        <div className="mx-auto mt-4 h-2 w-[100px] shrink-0 rounded-full bg-muted group-data-[vaul-drawer-direction=left]/drawer-content:hidden group-data-[vaul-drawer-direction=right]/drawer-content:hidden" />
        {needsFallbackTitle ? <DrawerTitle className="sr-only">Panel</DrawerTitle> : null}
        {children}
      </DrawerPrimitive.Content>
    </DrawerPortal>
  );
}

function DrawerBody({ className, ...props }: React.ComponentProps<'div'>) {
  // Same role as SheetBody: the part that scrolls, so the header/footer
  // stay put.
  return <div data-slot="drawer-body" className={cn('min-h-0 flex-1 overflow-y-auto', className)} {...props} />;
}

const DrawerHeader = ({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) => (
  <div data-slot="drawer-header" className={cn('grid gap-1.5 p-4 text-center sm:text-left', className)} {...props} />
);

const DrawerFooter = ({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) => (
  <div data-slot="drawer-footer" className={cn('mt-auto flex flex-col gap-2 p-4', className)} {...props} />
);

function DrawerTitle({ className, ...props }: React.ComponentProps<typeof DrawerPrimitive.Title>) {
  return (
    <DrawerPrimitive.Title
      data-slot="drawer-title"
      className={cn('text-lg font-semibold leading-tight tracking-normal', className)}
      {...props}
    />
  );
}

function DrawerDescription({ className, ...props }: React.ComponentProps<typeof DrawerPrimitive.Description>) {
  return (
    <DrawerPrimitive.Description
      data-slot="drawer-description"
      className={cn('text-sm text-muted-foreground', className)}
      {...props}
    />
  );
}

export {
  Drawer,
  DrawerBody,
  DrawerClose,
  DrawerContent,
  DrawerDescription,
  DrawerFooter,
  DrawerHeader,
  DrawerOverlay,
  DrawerPortal,
  DrawerTitle,
  DrawerTrigger,
};
