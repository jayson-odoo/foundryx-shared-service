'use client';

import { cn } from '@/lib/utils';
import { inputVariants } from '@/components/ui/input';
import type { VariantProps } from 'class-variance-authority';
import {
  composeRenderProps,
  DateFieldProps,
  DateField as DateFieldRa,
  DateInputProps as DateInputPropsRa,
  DateInput as DateInputRa,
  DateSegmentProps,
  DateSegment as DateSegmentRa,
  DateValue as DateValueRa,
  TimeFieldProps,
  TimeField as TimeFieldRa,
  TimeValue as TimeValueRa,
} from 'react-aria-components';
import { useFx } from '@/hooks/use-fx';
import { FX_FIELD_BOX } from '@/components/fx/fields/classes';

function DateField<T extends DateValueRa>({ className, children, ...props }: DateFieldProps<T>) {
  return (
    <DateFieldRa
      className={composeRenderProps(className, (className) => cn(className))}
      data-slot="datefield"
      {...props}
    >
      {children}
    </DateFieldRa>
  );
}

function TimeField<T extends TimeValueRa>({ className, children, ...props }: TimeFieldProps<T>) {
  return (
    <TimeFieldRa
      className={composeRenderProps(className, (className) => cn(className))}
      data-slot="datefield"
      {...props}
    >
      {children}
    </TimeFieldRa>
  );
}

function DateSegment({ className, ...props }: DateSegmentProps) {
  return (
    <DateSegmentRa
      className={composeRenderProps(className, (className) =>
        cn(
          `
            text-foreground inline-flex rounded px-0.5 caret-transparent outline-hidden data-[type=literal]:text-muted-foreground/70 data-[type=literal]:px-0
            data-placeholder:text-muted-foreground/70
            data-invalid:data-focused:bg-destructive data-invalid:data-placeholder:text-destructive data-invalid:text-destructive data-invalid:data-focused:data-placeholder:text-destructive-foreground data-invalid:data-focused:text-destructive-foreground 
            data-focused:bg-accent data-focused:data-placeholder:text-foreground data-focused:text-foreground             
            data-disabled:cursor-not-allowed data-disabled:opacity-50
          `,
          className,
        ),
      )}
      {...props}
      data-invalid
    />
  );
}

const dateInputStyles = `
  relative inline-flex items-center overflow-hidden whitespace-nowrap
  data-focus-within:ring-ring/30 data-focus-within:border-ring data-focus-within:outline-none data-focus-within:ring-[3px] 
  data-focus-within:has-aria-invalid:ring-destructive/20 dark:data-focus-within:has-aria-invalid:ring-destructive/40 data-focus-within:has-aria-invalid:border-destructive
`;

interface DateInputProps extends DateInputPropsRa, VariantProps<typeof inputVariants> {
  className?: string;
  variant?: VariantProps<typeof inputVariants>['variant'];
}

// Foundryx UIUX switch: the playbook field look while on; today's while off.
function DateInput(props: Omit<DateInputProps, 'children'>) {
  return useFx() ? <FxDateInput {...props} /> : <DateInputLegacy {...props} />;
}

const FX_DATE_INPUT_SIZE = {
  sm: 'h-7 px-2.5 text-xs pointer-coarse:text-base',
  md: 'h-8.5 px-3 text-[0.8125rem] pointer-coarse:text-base',
  lg: 'h-10 px-4 text-sm pointer-coarse:text-base',
} as const;

/** The segmented date input with the fx field box (hover lift, one focus ring). */
function FxDateInput({ className, variant = 'md', ...props }: Omit<DateInputProps, 'children'>) {
  return (
    <DateInputRa
      data-slot="input"
      data-fx-field=""
      className={composeRenderProps(className, (className) =>
        cn(
          FX_FIELD_BOX,
          FX_DATE_INPUT_SIZE[variant ?? 'md'],
          'relative w-full overflow-hidden whitespace-nowrap tabular-nums data-focus-within:border-(--fx-link) data-focus-within:ring-[3px] data-focus-within:ring-(--fx-link)/20',
          className,
        ),
      )}
      {...props}
    >
      {(segment) => <DateSegment segment={segment} />}
    </DateInputRa>
  );
}

function DateInputLegacy({ className, variant = 'md', ...props }: Omit<DateInputProps, 'children'>) {
  return (
    <DateInputRa
      data-slot="input"
      className={composeRenderProps(className, (className) =>
        cn(inputVariants({ variant }), dateInputStyles, className),
      )}
      {...props}
    >
      {(segment) => <DateSegment segment={segment} />}
    </DateInputRa>
  );
}

export { DateField, DateInput, DateSegment, TimeField, dateInputStyles };
export type { DateInputProps };
