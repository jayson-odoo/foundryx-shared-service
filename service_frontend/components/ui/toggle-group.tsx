'use client';

import * as React from 'react';
import { cn } from '@/lib/utils';
import { toggleVariants } from '@/components/ui/toggle';
import { type VariantProps } from 'class-variance-authority';
import { ToggleGroup as ToggleGroupPrimitive } from 'radix-ui';
import { useFx } from '@/hooks/use-fx';
import { FxToggleGroup, FxToggleGroupItem } from '@/components/fx/fields/fx-toggle-group';

const ToggleGroupContext = React.createContext<VariantProps<typeof toggleVariants>>({
  size: 'md',
  variant: 'default',
});

// Foundryx UIUX switch: the playbook segmented toggle while on; today's while off.
function ToggleGroup(props: React.ComponentProps<typeof ToggleGroupPrimitive.Root> & VariantProps<typeof toggleVariants>) {
  return useFx() ? <FxToggleGroup {...props} /> : <ToggleGroupLegacy {...props} />;
}

function ToggleGroupLegacy({
  className,
  variant,
  size,
  children,
  ...props
}: React.ComponentProps<typeof ToggleGroupPrimitive.Root> & VariantProps<typeof toggleVariants>) {
  return (
    <ToggleGroupPrimitive.Root
      data-slot="toggle-group"
      data-variant={variant}
      data-size={size}
      className={cn(
        'group/toggle-group flex items-center rounded-md gap-1 data-[variant=outline]:gap-0 data-[variant=outline]:shadow-xs',
        className,
      )}
      {...props}
    >
      <ToggleGroupContext.Provider value={{ variant, size }}>{children}</ToggleGroupContext.Provider>
    </ToggleGroupPrimitive.Root>
  );
}

// Foundryx UIUX switch: the playbook segmented toggle while on; today's while off.
function ToggleGroupItem(props: React.ComponentProps<typeof ToggleGroupPrimitive.Item> & VariantProps<typeof toggleVariants>) {
  return useFx() ? <FxToggleGroupItem {...props} /> : <ToggleGroupItemLegacy {...props} />;
}

function ToggleGroupItemLegacy({
  className,
  children,
  variant,
  size,
  ...props
}: React.ComponentProps<typeof ToggleGroupPrimitive.Item> & VariantProps<typeof toggleVariants>) {
  const context = React.useContext(ToggleGroupContext);

  return (
    <ToggleGroupPrimitive.Item
      data-slot="toggle-group-item"
      data-variant={context.variant || variant}
      data-size={context.size || size}
      className={cn(
        toggleVariants({
          variant: context.variant || variant,
          size: context.size || size,
        }),
        'shrink-0 shadow-none data-[variant=outline]:rounded-none data-[variant=outline]:first:rounded-s-md data-[variant=outline]:last:rounded-e-md focus:z-10 focus-visible:z-10 data-[variant=outline]:border-s-0 data-[variant=outline]:first:border-s',
        className,
      )}
      {...props}
    >
      {children}
    </ToggleGroupPrimitive.Item>
  );
}

export { ToggleGroup, ToggleGroupItem };
