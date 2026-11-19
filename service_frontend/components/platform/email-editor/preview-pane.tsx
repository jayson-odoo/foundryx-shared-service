'use client';

import { useCallback, useEffect, useState } from 'react';
import { Monitor, RefreshCw, Smartphone } from 'lucide-react';
import { Button } from '@/components/ui/button';
import type { TemplatePreview } from '@/services/template-service';
import { useFx } from '@/hooks/use-fx';
import { FxPreviewPane } from './fx-preview-pane';

export interface PreviewPaneProps {
  /** Runs the render pipeline (mock now; POST /templates/preview in Phase B). */
  render: () => Promise<TemplatePreview>;
}

export type PreviewWidth = 'desktop' | 'mobile';

export const WIDTHS: Record<PreviewWidth, number> = { desktop: 600, mobile: 375 };

export function PreviewPane(props: PreviewPaneProps) {
  // Foundryx UIUX switch: the playbook toggle and icon actions while on;
  // today's pane while off. Both render through `usePreviewRender`.
  return useFx() ? <FxPreviewPane {...props} /> : <PreviewPaneLegacy {...props} />;
}

/** Runs the render pipeline on mount and on Refresh (both looks). */
export function usePreviewRender(render: () => Promise<TemplatePreview>) {
  const [preview, setPreview] = useState<TemplatePreview | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    setIsLoading(true);
    setError(null);
    render()
      .then(setPreview)
      .catch((e: Error) => setError(e.message))
      .finally(() => setIsLoading(false));
  }, [render]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return { preview, isLoading, error, refresh };
}

function PreviewPaneLegacy({ render }: PreviewPaneProps) {
  const [width, setWidth] = useState<PreviewWidth>('desktop');
  const { preview, isLoading, error, refresh } = usePreviewRender(render);

  return (
    <div data-testid="preview-pane" className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1">
          <Button
            type="button"
            variant={width === 'desktop' ? 'primary' : 'outline'}
            size="sm"
            data-testid="preview-width-desktop"
            onClick={() => setWidth('desktop')}
          >
            <Monitor className="size-3.5" /> Desktop
          </Button>
          <Button
            type="button"
            variant={width === 'mobile' ? 'primary' : 'outline'}
            size="sm"
            data-testid="preview-width-mobile"
            onClick={() => setWidth('mobile')}
          >
            <Smartphone className="size-3.5" /> Mobile
          </Button>
        </div>
        <Button type="button" variant="outline" size="sm" onClick={refresh} disabled={isLoading}>
          <RefreshCw className={`size-3.5 ${isLoading ? 'animate-spin' : ''}`} /> Refresh
        </Button>
      </div>

      {preview && (
        <div className="rounded-md border border-input bg-muted/40 px-3 py-2 text-sm">
          <span className="text-xs uppercase tracking-wide text-muted-foreground">Subject: </span>
          <span className="font-medium" data-testid="preview-subject">
            {preview.subject || '(empty subject)'}
          </span>
        </div>
      )}

      {error ? (
        <div className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">
          {error}
        </div>
      ) : (
        <div className="flex justify-center overflow-auto rounded-md border border-input bg-zinc-100 p-4">
          {/* Sandboxed: preview HTML never executes scripts in the app origin. */}
          <iframe
            title="Email preview"
            data-testid="preview-frame"
            sandbox=""
            srcDoc={preview?.html ?? ''}
            style={{ width: WIDTHS[width] }}
            className="h-[640px] border-0 bg-white shadow-sm transition-[width]"
          />
        </div>
      )}
    </div>
  );
}
