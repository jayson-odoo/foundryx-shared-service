'use client';

/**
 * Branded email preview - renders a template through the SAME engine pipeline
 * used at send (brand header/footer/buttons + sample merge values), in a
 * sandboxed iframe. Used by the status-notification + workflow email pickers so
 * an operator can verify the real branded result of a linked template.
 */
import { useEffect, useState } from 'react';
import { ExternalLink, LoaderCircleIcon } from 'lucide-react';
import { Button } from '@/components/ui/button';

import { templateEngineService } from '@/services/template-service';
import { isCanvasDoc } from '@/types/templates';

export interface BrandedTemplatePreviewProps {
  templateId: string | null | undefined;
  /** Override the rendered subject (e.g. a per-use subject override). */
  subjectOverride?: string;
  className?: string;
}

/** Full block editor for a template (brand header/footer/buttons are editable). */
function templateEditHref(id: string): string {
  return `/settings/templates/${id}?edit=1`;
}

export function BrandedTemplatePreview({
  templateId,
  subjectOverride,
  className,
}: BrandedTemplatePreviewProps) {
  const [html, setHtml] = useState<string | null>(null);
  const [subject, setSubject] = useState('');
  const [status, setStatus] = useState<'idle' | 'loading' | 'error'>('idle');

  useEffect(() => {
    if (!templateId) {
      setHtml(null);
      setStatus('idle');
      return;
    }
    let cancelled = false;
    setStatus('loading');
    (async () => {
      try {
        const template = await templateEngineService.getTemplate(templateId);
        if (!template || isCanvasDoc(template.doc)) throw new Error('not found');
        const subj = subjectOverride?.trim() ? subjectOverride : template.subject;
        const rendered = await templateEngineService.preview(template.doc, template.context, subj);
        if (cancelled) return;
        setSubject(rendered.subject);
        setHtml(rendered.html);
        setStatus('idle');
      } catch {
        if (!cancelled) setStatus('error');
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [templateId, subjectOverride]);

  if (!templateId) {
    return (
      <div className={className}>
        <p className="text-xs text-muted-foreground">Select a template to preview it.</p>
      </div>
    );
  }
  if (status === 'loading') {
    return (
      <div className={`flex items-center justify-center py-10 ${className ?? ''}`}>
        <LoaderCircleIcon className="size-5 animate-spin text-muted-foreground" />
      </div>
    );
  }
  if (status === 'error') {
    return (
      <div className={className}>
        <p className="text-xs text-destructive">Couldn’t render this template.</p>
      </div>
    );
  }
  return (
    <div className={`flex flex-col gap-2 ${className ?? ''}`}>
      <div className="flex items-center justify-between gap-2">
        <div className="min-w-0 flex-1 rounded-md border border-dashed border-input bg-muted/40 px-3 py-1.5 text-sm font-medium text-foreground">
          {subject || <span className="font-normal text-muted-foreground">(no subject)</span>}
        </div>
        <Button variant="outline" size="sm" className="shrink-0" asChild>
          <a href={templateEditHref(templateId)} target="_blank" rel="noopener noreferrer">
            <ExternalLink className="size-3.5" /> Edit template
          </a>
        </Button>
      </div>
      <iframe
        title="Email preview"
        sandbox=""
        srcDoc={html ?? ''}
        className="h-96 w-full rounded-md border border-input bg-white"
      />
    </div>
  );
}
