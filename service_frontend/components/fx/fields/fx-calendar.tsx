'use client';

/**
 * The Foundryx UIUX month calendar (playbook 0.71.0 "Date fields > The
 * calendar"): styled like the menus, today has a ring, the chosen day is
 * filled in the link colour, days outside the allowed range are muted and
 * can't be picked, and a range tints the days between. Keys come from the
 * calendar itself: arrows a day or a week, Page Up/Down a month, Home/End the
 * week's ends, Enter picks. `Calendar` renders it while the switch is on.
 */
import * as React from 'react';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { DayPicker } from 'react-day-picker';
import { cn } from '@/lib/utils';
import { PRESSED_CLASS } from '@/components/ui/primitive-classes';

const NAV =
  `${PRESSED_CLASS} inline-flex size-8 items-center justify-center rounded-(--fx-r-s) text-(--fx-ink-2) hover:bg-(--fx-surface-2) hover:text-(--fx-ink) disabled:opacity-40`;

export function FxCalendar({
  className,
  classNames,
  showOutsideDays = true,
  ...props
}: React.ComponentProps<typeof DayPicker>) {
  return (
    <DayPicker
      showOutsideDays={showOutsideDays}
      data-fx-calendar=""
      className={cn('p-3 text-(--fx-ink)', className)}
      classNames={{
        months: 'relative flex flex-col sm:flex-row gap-4',
        month: 'w-full',
        month_caption: 'relative mx-10 mb-1 flex h-8 items-center justify-center',
        caption_label: 'text-sm font-semibold',
        nav: 'absolute top-0 flex w-full justify-between',
        button_previous: NAV,
        button_next: NAV,
        weekday: 'size-9 p-0 text-xs font-medium text-(--fx-ink-3) pointer-coarse:size-11',
        day: 'group size-9 px-0 py-px text-sm pointer-coarse:size-11',
        day_button:
          'relative flex size-9 cursor-pointer items-center justify-center rounded-(--fx-r-s) p-0 tabular-nums text-(--fx-ink) outline-none pointer-coarse:size-11 ' +
          'transition-[background-color,color] duration-(--fx-t-hover) ease-(--fx-ease-out) ' +
          'hover:not-in-data-selected:bg-(--fx-surface-2) focus-visible:ring-2 focus-visible:ring-(--fx-link) ' +
          'group-data-today:ring-1 group-data-today:ring-inset group-data-today:ring-(--fx-link) ' +
          'group-data-selected:bg-(--fx-link) group-data-selected:font-semibold group-data-selected:text-white ' +
          'group-data-outside:text-(--fx-ink-3) group-data-disabled:pointer-events-none group-data-disabled:text-(--fx-ink-3) group-data-disabled:opacity-50 ' +
          'group-[.range-middle]:rounded-none group-[.range-middle]:group-data-selected:bg-(--fx-link-bg) group-[.range-middle]:group-data-selected:font-normal group-[.range-middle]:group-data-selected:text-(--fx-ink) ' +
          'group-[.range-start:not(.range-end)]:rounded-e-none group-[.range-end:not(.range-start)]:rounded-s-none',
        range_start: 'range-start',
        range_end: 'range-end',
        range_middle: 'range-middle',
        today: '',
        outside: '',
        hidden: 'invisible',
        week_number: 'size-9 p-0 text-xs text-(--fx-ink-3)',
        ...classNames,
      }}
      components={{
        Chevron: (chevron) =>
          chevron.orientation === 'left' ? (
            <ChevronLeft className="size-4 rtl:rotate-180" />
          ) : (
            <ChevronRight className="size-4 rtl:rotate-180" />
          ),
      }}
      {...props}
    />
  );
}
