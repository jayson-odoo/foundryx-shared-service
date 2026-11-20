'use client';

import { X } from 'lucide-react';
import { Button } from '@/components/ui/button';

export interface PanelHeaderProps {
  title: string;
  subtitle?: string;
  onClose: () => void;
}

/** The panel's own chrome (AC-WEB-47) - a header title + optional tenant
 *  name, no vendor mark, no instructional copy. */
export function PanelHeader({ title, subtitle, onClose }: PanelHeaderProps) {
  return (
    <div className="flex shrink-0 items-center justify-between gap-2 border-b border-border bg-primary px-4 py-3 text-primary-foreground">
      <div className="min-w-0">
        <p className="truncate font-heading text-sm font-semibold">{title}</p>
        {subtitle && <p className="truncate text-xs text-primary-foreground/80">{subtitle}</p>}
      </div>
      <Button
        type="button"
        variant="ghost"
        size="icon"
        onClick={onClose}
        aria-label="Close chat"
        className="shrink-0 text-primary-foreground hover:bg-primary-active hover:text-primary-foreground"
        data-testid="webchat-close"
      >
        <X className="size-4" />
      </Button>
    </div>
  );
}
