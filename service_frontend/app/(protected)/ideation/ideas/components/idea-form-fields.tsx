'use client';

import { useState } from 'react';
import Link from 'next/link';
import type { UseFormReturn } from 'react-hook-form';
import {
  FileText,
  Film,
  ImageIcon,
  Mic,
  Paperclip,
} from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { PRESSED_CLASS } from '@/components/ui/primitive-classes';
import { cn } from '@/lib/utils';
import { Card, CardContent } from '@/components/ui/card';
import { FormControl, FormField, FormItem, FormMessage } from '@/components/ui/form';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { ClampedText } from '@/components/platform/clamped-text';
import { SearchSelect } from '@/components/platform/search-select';
import { FormRow } from '@/components/platform/resource-form';
import { useDatetime } from '@/hooks/use-datetime';
import { useIdeationRuntime } from '@/hooks/use-ideation-runtime';
import { AttachmentDrop } from './attachment-drop';
import { IdeaAttachmentPreviewDialog } from './idea-attachment-preview-dialog';
import { IdeaComments } from './idea-comments';
import {
  IDEA_SOURCE_LABEL,
  type Idea,
  type IdeaAttachment,
  type IdeaAttachmentKind,
  type Product,
} from '@/types/ideation';
import type { IdeaFormValues } from './idea-schema';

export interface DetailsTabProps {
  form: UseFormReturn<IdeaFormValues>;
  editing: boolean;
  creating: boolean;
  idea: Idea | null;
  products: Product[];
  /** Whether the viewer may comment - resolved by the form hook (it already
   * reads the session). Omitted = read-only thread. */
  canComment?: boolean;
}

/** The Details tab: the fields card, then (view mode, existing idea only) the
 * Comments section under it (plan 19, AC-19-21). The vote box lives in the
 * header avatar slot, not here (AC-19-16). */
export function DetailsTab(props: DetailsTabProps) {
  const { editing, creating, idea } = props;
  return (
    <div className="flex flex-col gap-5">
      <DetailsFields {...props} />
      {!editing && !creating && idea && (
        <Card>
          <CardContent className="pb-4 pt-0">
            <IdeaComments
              ideaId={idea.id}
              mergedChild={Boolean(idea.mergedIntoId)}
              canComment={props.canComment ?? false}
            />
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function DetailsFields({ form, editing, creating, idea, products }: DetailsTabProps) {
  const productOptions = products.map((p) => ({ label: p.name, value: p.id }));
  // Runtime-aware href (BLOCKER 1, issue #94 review round 1) - the CRM embed
  // iframe has no operator session, so the "Merged into" link must resolve
  // to `/embed/ideas/<id>`, never the bare operator path.
  const { paths } = useIdeationRuntime();
  const { formatDateTime } = useDatetime();

  return (
    <Card>
      <CardContent className="py-1">
        <FormRow label="Problem statement" required={editing}>
          {editing ? (
            <FormField
              control={form.control}
              name="problem"
              render={({ field }) => (
                <FormItem className="max-w-xl">
                  <FormControl>
                    <Textarea rows={3} placeholder="The problem or observation" {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
          ) : (
            <span className="whitespace-pre-wrap">{idea?.problem || '-'}</span>
          )}
        </FormRow>

        <FormRow label="Proposed solution">
          {editing ? (
            <FormField
              control={form.control}
              name="proposedSolution"
              render={({ field }) => (
                <FormItem className="max-w-xl">
                  <FormControl>
                    <Textarea rows={3} placeholder="How could we solve it?" {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
          ) : (
            <span className="whitespace-pre-wrap text-muted-foreground">
              {idea?.proposedSolution || '-'}
            </span>
          )}
        </FormRow>

        <FormRow label="Impact">
          {editing ? (
            <FormField
              control={form.control}
              name="impact"
              render={({ field }) => (
                <FormItem className="max-w-xl">
                  <FormControl>
                    <Textarea rows={3} placeholder="What does solving it improve?" {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
          ) : (
            <span className="whitespace-pre-wrap text-muted-foreground">
              {idea?.impact || '-'}
            </span>
          )}
        </FormRow>

        <FormRow label="Department">
          {editing ? (
            <FormField
              control={form.control}
              name="department"
              render={({ field }) => (
                <FormItem className="max-w-sm">
                  <FormControl>
                    <Input placeholder="Which team is this for?" {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
          ) : (
            (idea?.department || '-')
          )}
        </FormRow>

        {/* A new idea needs a product; an existing idea keeps its saved one. */}
        {creating && (
          <FormRow label="Product" required={editing}>
            {editing ? (
              <FormField
                control={form.control}
                name="productId"
                render={({ field }) => (
                  <FormItem className="max-w-sm">
                    <FormControl>
                      <SearchSelect
                        options={productOptions}
                        value={field.value}
                        onChange={field.onChange}
                        placeholder="Select a product…"
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            ) : idea ? (
              <Badge variant="secondary">{idea.productName}</Badge>
            ) : (
              '-'
            )}
          </FormRow>
        )}

        {idea?.mergedInto && (
          <FormRow label="Merged into">
            <Link
              href={paths.formHref(idea.mergedInto.id)}
              className="text-sm font-medium text-primary hover:underline"
            >
              {idea.mergedInto.ideaNumber ?? idea.mergedInto.title}
            </Link>
          </FormRow>
        )}

        <FormRow label="Submitter">{idea?.submitterName ?? '-'}</FormRow>

        <FormRow label="Channel">
          {idea ? (
            <Badge variant="outline" appearance="light">
              {IDEA_SOURCE_LABEL[idea.source]}
            </Badge>
          ) : (
            '-'
          )}
        </FormRow>

        <FormRow label="Priority">
          {idea && idea.rank != null ? <span className="tabular-nums">#{idea.rank}</span> : '-'}
        </FormRow>

        <FormRow label="Raw notes">
          {editing ? (
            <FormField
              control={form.control}
              name="rawText"
              render={({ field }) => (
                <FormItem className="max-w-xl">
                  <FormControl>
                    <Textarea rows={4} placeholder="Verbatim capture / context" {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
          ) : (
            <span className="whitespace-pre-wrap text-muted-foreground">
              {idea?.rawText || '-'}
            </span>
          )}
        </FormRow>

        <FormRow label="Captured">
          {idea ? formatDateTime(idea.createdAt) : '-'}
        </FormRow>
      </CardContent>
    </Card>
  );
}

const ATTACHMENT_ICON: Record<IdeaAttachmentKind, typeof FileText> = {
  audio: Mic,
  image: ImageIcon,
  video: Film,
  file: FileText,
};

function formatSize(bytes?: number): string {
  if (!bytes) return '';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export interface AttachmentsTabProps {
  attachments: IdeaAttachment[];
  /** When set, the drop area is shown and each drop is uploaded immediately. */
  onUpload?: (files: File[]) => Promise<void>;
  /** Fetches an uploaded attachment's bytes for the preview/download. */
  fetchContent?: (attachment: IdeaAttachment) => Promise<Blob>;
}

export function AttachmentsTab({ attachments, onUpload, fetchContent }: AttachmentsTabProps) {
  const [preview, setPreview] = useState<IdeaAttachment | null>(null);
  const drop = onUpload ? (
    <AttachmentDrop onFiles={(files) => void onUpload(files)} />
  ) : null;

  if (attachments.length === 0) {
    return (
      <div className="space-y-3">
        {drop}
        <Card>
          <CardContent className="flex flex-col items-center justify-center gap-2 py-16 text-center">
            <Paperclip className="size-8 text-muted-foreground" />
            <p className="text-sm font-medium">No attachments</p>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {drop}
      <Card>
        <CardContent className="py-3">
          <ul className="divide-y divide-border">
            {attachments.map((a) => {
              const Icon = ATTACHMENT_ICON[a.kind];
              const meta = [
                a.durationSec ? `${a.durationSec}s` : null,
                formatSize(a.sizeBytes),
              ]
                .filter(Boolean)
                .join(' · ');
              return (
                <li key={a.id} className="py-1.5">
                  <button
                    type="button"
                    onClick={() => setPreview(a)}
                    className={cn(
                      PRESSED_CLASS,
                      'flex w-full items-center gap-3 rounded-md px-2 py-1.5 text-left transition-colors hover:bg-muted/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                    )}
                    title={`Preview ${a.name}`}
                  >
                    <span className="flex size-9 shrink-0 items-center justify-center rounded-md bg-muted">
                      <Icon className="size-4 text-muted-foreground" />
                    </span>
                    <div className="min-w-0 flex-1">
                      <ClampedText text={a.name} lines={1} className="text-sm font-medium" />
                      {meta && <p className="text-xs text-muted-foreground">{meta}</p>}
                    </div>
                    <Badge variant="outline" appearance="light" className="capitalize">
                      {a.kind}
                    </Badge>
                  </button>
                </li>
              );
            })}
          </ul>
        </CardContent>
        <IdeaAttachmentPreviewDialog
          attachment={preview}
          onClose={() => setPreview(null)}
          fetchContent={fetchContent}
        />
      </Card>
    </div>
  );
}
