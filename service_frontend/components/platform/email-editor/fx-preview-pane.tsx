'use client';

/**
 * The email preview with the Foundryx UIUX switch on: Desktop / Mobile as the
 * playbook's segmented toggle, Refresh as an icon action, the subject on its
 * own line and the rendered email in the same sandboxed frame (it never runs
 * scripts in the app). The render request is the legacy pane's
 * (`usePreviewRender`).
 */
import { useState } from 'react';
import { Loader2, Monitor, Smartphone } from 'lucide-react';
import { cn } from '@/lib/utils';
import { FxIconAction } from '@/components/fx/actions/icon-action';
import { FxToggleGroup, FxToggleGroupItem } from '@/components/fx/fields/fx-toggle-group';
import type { TemplatePreview } from '@/services/template-service';
import { usePreviewRender, WIDTHS, type PreviewWidth } from './preview-pane';

export interface FxPreviewPaneProps {
  render: () => Promise<TemplatePreview>;
  /** The width it opens at (the preview beside the editor opens at Mobile). */
  initialWidth?: PreviewWidth;
  /** Shorter frame, for the preview beside the editor. */
  compact?: boolean;
  className?: string;
}

export function FxPreviewPane({ render, initialWidth = 'desktop', compact, className }: FxPreviewPaneProps) {
  const [width, setWidth] = useState<PreviewWidth>(initialWidth);
  const { preview, isLoading, error, refresh } = usePreviewRender(render);

  return (
    <div data-testid="preview-pane" className={cn('flex min-w-0 flex-col gap-3', className)}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <FxToggleGroup
          type="single"
          size="sm"
          aria-label="Preview width"
          value={width}
          onValueChange={(v) => v && setWidth(v as PreviewWidth)}
        >
          <FxToggleGroupItem value="desktop" data-testid="preview-width-desktop">
            <Monitor aria-hidden="true" className="size-3.5" /> Desktop
          </FxToggleGroupItem>
          <FxToggleGroupItem value="mobile" data-testid="preview-width-mobile">
            <Smartphone aria-hidden="true" className="size-3.5" /> Mobile
          </FxToggleGroupItem>
        </FxToggleGroup>
        <FxIconAction
          mini
          label={isLoading ? 'Refreshing the preview' : 'Refresh preview'}
          icon="refresh"
          iconNode={isLoading ? <Loader2 aria-hidden="true" className="size-[18px] animate-spin" /> : undefined}
          disabledReason={isLoading ? 'Refreshing the preview' : undefined}
          onClick={refresh}
        />
      </div>

      {preview && (
        <p className="text-sm text-(--fx-ink-2) [overflow-wrap:anywhere]">
          <span className="text-(--fx-ink-3)">Subject </span>
          <span className="font-semibold text-(--fx-ink)" data-testid="preview-subject">
            {preview.subject || 'No subject'}
          </span>
        </p>
      )}

      {error ? (
        <p role="alert" className="text-sm font-semibold text-[color-mix(in_srgb,var(--fx-act)_82%,var(--fx-surface))]">
          {error}
        </p>
      ) : (
        <div className="flex justify-center overflow-auto rounded-(--fx-r-l) border border-(--fx-line) bg-(--fx-surface-2) p-3">
          {/* Sandboxed: preview HTML never executes scripts in the app origin. */}
          <iframe
            title="Email preview"
            data-testid="preview-frame"
            sandbox=""
            srcDoc={preview?.html ?? ''}
            style={{ width: WIDTHS[width] }}
            className={cn(
              'shrink-0 border-0 bg-white shadow-sm transition-[width] duration-(--fx-t-layout) ease-(--fx-ease-out)',
              compact ? 'h-[520px]' : 'h-[640px]',
            )}
          />
        </div>
      )}
    </div>
  );
}
