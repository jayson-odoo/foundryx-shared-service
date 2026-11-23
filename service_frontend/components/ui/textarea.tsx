'use client';

import * as React from 'react';
import { cn } from '@/lib/utils';
import { cva, type VariantProps } from 'class-variance-authority';
import { useFx } from '@/hooks/use-fx';
import { FxTextarea } from '@/components/fx/fields/fx-input';

// Define input size variants
const textareaVariants = cva(
  `
    w-full bg-background border border-input bg-background text-foreground shadow-xs shadow-black/5 transition-[color,box-shadow] 
    text-foreground placeholder:text-muted-foreground/80 focus-visible:border-ring focus-visible:outline-none focus-visible:ring-[3px] 
    focus-visible:ring-ring/30 disabled:cursor-not-allowed disabled:opacity-50 [&[readonly]]:opacity-70 aria-invalid:border-destructive
    aria-invalid:border-destructive/60 aria-invalid:ring-destructive/10 dark:aria-invalid:border-destructive dark:aria-invalid:ring-destructive/20
  `,
  {
    variants: {
      variant: {
        sm: 'px-2.5 py-2.5 text-xs rounded-md',
        md: 'px-3 py-3 text-[0.8125rem] leading-(--text-sm--line-height) rounded-md',
        lg: 'px-4 py-4 text-sm rounded-md',
      },
    },
    defaultVariants: {
      variant: 'md',
    },
  },
);

// Foundryx UIUX switch: the playbook field while on; today's text area while off.
function Textarea(props: React.ComponentProps<'textarea'> & VariantProps<typeof textareaVariants>) {
  return useFx() ? <FxTextarea {...props} /> : <TextareaLegacy {...props} />;
}

function TextareaLegacy({
  className,
  variant,
  ...props
}: React.ComponentProps<'textarea'> & VariantProps<typeof textareaVariants>) {
  return <textarea data-slot="textarea" className={cn(textareaVariants({ variant }), className)} {...props} />;
}

export { Textarea, textareaVariants };
