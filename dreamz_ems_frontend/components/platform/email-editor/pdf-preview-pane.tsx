'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { Download, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';

/**
 * Document preview pane (F2 D7) — our OWN renderer, not the browser's native
 * PDF viewer. The backend compiles the document to its print HTML (the exact
 * input WeasyPrint consumes) and we show it via `srcDoc` in a fully-sandboxed
 * iframe (`sandbox=""` — same pattern as the email preview pane: scripts never
 * run, tenant content is also nh3-sanitized at save) styled as a paper sheet —
 * no browser PDF-viewer chrome. On-demand "Refresh" (NOT per-keystroke).
 * "Download PDF" fetches the authoritative WeasyPrint bytes.
 */

export interface PdfPreviewPaneProps {
  /** Renders the draft to preview HTML (POST /templates/preview?format=docHtml). */
  renderHtml: () => Promise<string>;
  /** Fetches the authoritative PDF bytes for download (format=pdf). */
  downloadPdf?: () => Promise<Blob>;
}

export function PdfPreviewPane({ renderHtml, downloadPdf }: PdfPreviewPaneProps) {
  const [html, setHtml] = useState<string>('');
  const [isLoading, setIsLoading] = useState(false);
  const [isDownloading, setIsDownloading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Keep the latest renderHtml without making `refresh` change identity — the
  // prop is an inline arrow (new each parent render). A stable `refresh` is what
  // makes the mount effect fire ONCE (not on every re-render, which raced
  // overlapping requests and could blank the pane when a stale one resolved).
  const renderRef = useRef(renderHtml);
  renderRef.current = renderHtml;
  // Monotonic id so only the most-recent request may write state.
  const reqId = useRef(0);

  const refresh = useCallback(() => {
    const id = ++reqId.current;
    setIsLoading(true);
    setError(null);
    renderRef
      .current()
      .then((h) => {
        if (id === reqId.current) setHtml(h);
      })
      .catch((e: Error) => {
        if (id === reqId.current) setError(e.message || 'Preview failed to render.');
      })
      .finally(() => {
        if (id === reqId.current) setIsLoading(false);
      });
  }, []);

  // Render once on mount; thereafter only on explicit Refresh.
  useEffect(() => {
    refresh();
  }, [refresh]);

  const download = useCallback(() => {
    if (!downloadPdf) return;
    setIsDownloading(true);
    setError(null);
    downloadPdf()
      .then((blob) => {
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'document.pdf';
        a.click();
        URL.revokeObjectURL(url);
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setIsDownloading(false));
  }, [downloadPdf]);

  return (
    <div data-testid="pdf-preview-pane" className="flex flex-col gap-3">
      <div className="flex items-center justify-end gap-2">
        <Button type="button" variant="outline" size="sm" onClick={refresh} disabled={isLoading}>
          <RefreshCw className={`size-3.5 ${isLoading ? 'animate-spin' : ''}`} /> Refresh preview
        </Button>
        {downloadPdf && (
          <Button type="button" size="sm" onClick={download} disabled={isDownloading}>
            <Download className="size-3.5" /> Download PDF
          </Button>
        )}
      </div>

      {error ? (
        <div className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">
          {error}
        </div>
      ) : (
        <div className="overflow-auto rounded-md border border-input bg-zinc-100">
          <iframe
            title="Document preview"
            data-testid="pdf-preview-frame"
            srcDoc={html}
            sandbox=""
            className="h-[720px] w-full border-0"
          />
        </div>
      )}
    </div>
  );
}
