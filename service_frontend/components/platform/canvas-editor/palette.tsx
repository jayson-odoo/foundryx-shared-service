'use client';

import {
  Type,
  ImageIcon,
  Square,
  QrCode,
  Minus,
  Share2,
  Code,
  PanelTop,
  PanelBottom,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  CollapsiblePalette,
  type PaletteCategory,
} from '@/components/platform/palette/collapsible-palette';
import type { CanvasElementType } from '@/types/templates';

/** Grouped / collapsible / searchable element palette (house pattern, matching
 * the form + email builders). Click-to-add drops at canvas centre, unwired. */

const META: Record<CanvasElementType, { label: string; icon: typeof Type }> = {
  text: { label: 'Text', icon: Type },
  image: { label: 'Image', icon: ImageIcon },
  qr: { label: 'QR code', icon: QrCode },
  shape: { label: 'Shape', icon: Square },
  divider: { label: 'Divider', icon: Minus },
  socialLinks: { label: 'Social links', icon: Share2 },
  brandHeader: { label: 'Brand header', icon: PanelTop },
  brandFooter: { label: 'Brand footer', icon: PanelBottom },
  customHtml: { label: 'Custom HTML', icon: Code },
};

const CATEGORIES: PaletteCategory<CanvasElementType>[] = [
  { id: 'content', label: 'Content', types: ['text', 'image', 'qr'] },
  { id: 'shapes', label: 'Shapes', types: ['shape', 'divider'] },
  { id: 'branding', label: 'Branding', types: ['brandHeader', 'brandFooter', 'socialLinks'] },
  { id: 'advanced', label: 'Advanced', types: ['customHtml'] },
];

export function elementLabel(type: CanvasElementType): string {
  return META[type]?.label ?? type;
}

export interface CanvasPaletteProps {
  disabled?: boolean;
  onAdd: (type: CanvasElementType) => void;
}

export function CanvasPalette({ disabled, onAdd }: CanvasPaletteProps) {
  return (
    <CollapsiblePalette
      testId="canvas-palette"
      searchPlaceholder="Search elements"
      categories={CATEGORIES}
      defaultOpenIds={['content']}
      labelFor={elementLabel}
      renderItem={(type) => {
        const Icon = META[type].icon;
        return (
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={disabled}
            className="w-full justify-start gap-2"
            data-testid={`palette-add-${type}`}
            onClick={() => onAdd(type)}
          >
            <Icon className="size-4" /> {META[type].label}
          </Button>
        );
      }}
    />
  );
}
