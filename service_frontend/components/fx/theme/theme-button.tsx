'use client';

/**
 * Where the Foundryx UIUX switch lives (playbook-uiux.md): the Theme button,
 * the one thing the playbook adds to SS while the switch is off.
 *
 * - Wider screens: a palette icon button in the top bar (tooltip "Theme")
 *   opening the Theme panel.
 * - Phones (the top bar's narrow layout): the 375px top bar has no room left
 *   for another icon, so the same panel opens from a "Theme" row in the user
 *   menu, under Dark Mode, in a dialog.
 *
 * Both carry `data-fx-entry`, the marker the switch-off parity snapshots drop
 * (components/fx/__parity__/parity-utils.ts). Both render nothing outside the
 * switch provider or inside `<FxOff>`.
 */
import { Palette } from 'lucide-react';
import { cn } from '@/lib/utils';
import { useFxControls } from '@/hooks/use-fx';
import { useIsMobile } from '@/hooks/use-mobile';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog';
import { DropdownMenuItem } from '@/components/ui/dropdown-menu';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { ThemePanel } from './theme-panel';

/** The floating panel's look: today's popover while off; see-through
 *  (50% surface, 6px blur) on the playbook palette while on. The explicit
 *  background replaces the primitive's own (tailwind-merge) and equals what
 *  `fx-see-through` sets; that class also marks it for the reduced
 *  transparency fallback in css/styles.css. */
const SEE_THROUGH = 'fx-see-through bg-(--fx-surface)/50 text-(--fx-ink)';

function panelClass(on: boolean): string {
  return on
    ? cn(
        SEE_THROUGH,
        'w-80 rounded-(--fx-r-l) border-(--fx-line) shadow-[0_8px_24px_var(--fx-shade)]',
      )
    : 'w-72';
}

const TITLE_CLASS = 'mb-3 text-sm font-semibold';

export function ThemeButton() {
  const fx = useFxControls();
  if (!fx) return null;
  return (
    <Popover>
      <Tooltip>
        <TooltipTrigger asChild>
          <PopoverTrigger asChild>
            <Button
              data-fx-entry=""
              variant="ghost"
              mode="icon"
              shape="circle"
              aria-label="Theme"
              className="size-9 hover:bg-primary/10 hover:[&_svg]:text-primary"
            >
              <Palette className="size-4.5!" />
            </Button>
          </PopoverTrigger>
        </TooltipTrigger>
        <TooltipContent>Theme</TooltipContent>
      </Tooltip>
      <PopoverContent
        align="end"
        aria-label="Theme"
        className={panelClass(fx.on)}
      >
        <p className={TITLE_CLASS}>Theme</p>
        <ThemePanel />
      </PopoverContent>
    </Popover>
  );
}

/** The phone entry: a "Theme" row for the user menu. */
export function ThemeMenuItem({ onOpen }: { onOpen: () => void }) {
  const fx = useFxControls();
  const mobile = useIsMobile();
  if (!fx || !mobile) return null;
  return (
    <DropdownMenuItem
      data-fx-entry=""
      className="flex items-center gap-2"
      onSelect={() => onOpen()}
    >
      <Palette />
      Theme
    </DropdownMenuItem>
  );
}

/** The phone panel: the same Theme panel in a dialog. */
export function ThemeDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const fx = useFxControls();
  if (!fx) return null;
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={cn('max-w-sm', fx.on && SEE_THROUGH)}>
        <DialogTitle className={TITLE_CLASS}>Theme</DialogTitle>
        <ThemePanel />
      </DialogContent>
    </Dialog>
  );
}
