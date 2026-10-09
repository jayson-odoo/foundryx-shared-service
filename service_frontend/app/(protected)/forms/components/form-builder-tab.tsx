'use client';

/** Builder tab (plan sprint-3/01 D18): primary toolbar (Preview / Publish /
 * Unpublish + state badges) above the builder. Preview renders the DRAFT
 * (author-only, D9); Publish runs the validate gate and snapshots a version. */
import { Check, CloudOff, CloudUpload, Eye, Link2 } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { FormBuilder } from '@/components/platform/form-builder';
import { useCopyToClipboard } from '@/hooks/use-copy-to-clipboard';
import type { FormDetail, FormDocument } from '@/types/forms';
import { formFillPath, publicFormFillPath } from './paths';

export interface FormBuilderTabProps {
  form: FormDetail;
  doc: FormDocument;
  onDocChange: (doc: FormDocument) => void;
  editing: boolean;
  canManage: boolean;
  busy: boolean;
  onPreview: () => void;
  onPublish: () => void;
  onUnpublish: () => void;
  /** Publish-gate problems from the last refused publish (cleared on edit). */
  publishProblems: string[];
}

export function FormBuilderTab({
  form,
  doc,
  onDocChange,
  editing,
  canManage,
  busy,
  onPreview,
  onPublish,
  onUnpublish,
  publishProblems,
}: FormBuilderTabProps) {
  const isPublished = form.status === 'published' && form.currentVersionId !== null;
  const { isCopied, copyToClipboard } = useCopyToClipboard();

  return (
    <div className="flex flex-col gap-3" data-testid="form-builder-tab">
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border bg-muted/30 px-3 py-2">
        <div className="flex items-center gap-2">
          {isPublished ? (
            <Badge variant="success" appearance="light" size="sm">
              Published · v{form.currentVersionNumber}
            </Badge>
          ) : (
            <Badge variant="secondary" appearance="light" size="sm">
              Draft
            </Badge>
          )}
          {isPublished && form.hasUnpublishedChanges && (
            <Badge variant="warning" appearance="light" size="sm" data-testid="unpublished-changes">
              Unpublished changes
            </Badge>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {isPublished && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                // Public forms expose the anonymous /public/forms/{slug} surface
                // (the embed contract); internal forms use the authed fill page.
                const path =
                  form.access === 'public'
                    ? publicFormFillPath(form.slug)
                    : formFillPath(form.id);
                copyToClipboard(`${window.location.origin}${path}`);
              }}
              data-testid="copy-fill-link"
            >
              {isCopied ? <Check className="size-3.5 text-green-600" /> : <Link2 className="size-3.5" />}{' '}
              {form.access === 'public' ? 'Public link' : 'Fill link'}
            </Button>
          )}
          <Button variant="outline" size="sm" onClick={onPreview} data-testid="preview-form">
            <Eye className="size-3.5" /> Preview
          </Button>
          {canManage && (
            <>
              <Button
                size="sm"
                onClick={onPublish}
                disabled={busy || (isPublished && !form.hasUnpublishedChanges)}
                data-testid="publish-form"
              >
                <CloudUpload className="size-3.5" /> Publish
              </Button>
              {isPublished && (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={onUnpublish}
                  disabled={busy}
                  data-testid="unpublish-form"
                >
                  <CloudOff className="size-3.5" /> Unpublish
                </Button>
              )}
            </>
          )}
        </div>
      </div>

      {publishProblems.length > 0 && (
        <div
          className="rounded-lg border border-destructive/40 bg-destructive/5 px-3 py-2"
          data-testid="publish-problems"
        >
          <p className="text-sm font-medium text-destructive">Publish blocked:</p>
          <ul className="mt-1 list-inside list-disc text-sm text-destructive/90">
            {publishProblems.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        </div>
      )}

      <FormBuilder doc={doc} onChange={onDocChange} editing={editing} />
    </div>
  );
}
