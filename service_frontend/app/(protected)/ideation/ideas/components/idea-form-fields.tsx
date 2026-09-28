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
import { SearchSelect } from '@/components/platform/search-select';
import { FormRow } from '@/components/platform/resource-form';
import { IdeaAttachmentPreviewDialog } from './idea-attachment-preview-dialog';
import { VoteCell } from './vote-cell';
import {
  IDEA_SOURCE_LABEL,
  type Idea,
  type IdeaAttachment,
  type IdeaAttachmentKind,
  type Product,
} from '@/types/ideation';
import type { IdeaFormValues } from './idea-schema';
import { ideaFormHref } from './paths';

export interface DetailsTabProps {
  form: UseFormReturn<IdeaFormValues>;
  editing: boolean;
  creating: boolean;
  idea: Idea | null;
  products: Product[];
  /** Wired by the caller so the form's vote control calls through the SAME
   * hook/service path as the list (issue #94, ideation round 2, AC-94-35).
   * Omitted on a harness that never exercises voting. */
  onVote?: (idea: Idea, dir: 'up' | 'down') => void;
}

export function DetailsTab({ form, editing, idea, products, onVote }: DetailsTabProps) {
  const productOptions = products.map((p) => ({ label: p.name, value: p.id }));

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

        {idea?.mergedInto && (
          <FormRow label="Merged into">
            <Link
              href={ideaFormHref(idea.mergedInto.id)}
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

        <FormRow label="Votes">
          {idea ? (
            <VoteCell
              idea={idea}
              onVote={(i, dir) => onVote?.(i, dir)}
              disabled={Boolean(idea.mergedIntoId)}
            />
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
          {idea ? new Date(idea.createdAt).toLocaleString() : '-'}
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

export function AttachmentsTab({ attachments }: { attachments: IdeaAttachment[] }) {
  const [preview, setPreview] = useState<IdeaAttachment | null>(null);

  if (attachments.length === 0) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center justify-center gap-2 py-16 text-center">
          <Paperclip className="size-8 text-muted-foreground" />
          <p className="text-sm font-medium">No attachments</p>
          <p className="text-sm text-muted-foreground">
            Voice notes, images, and videos captured with the idea will appear here.
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
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
                    <p className="truncate text-sm font-medium">{a.name}</p>
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
      <IdeaAttachmentPreviewDialog attachment={preview} onClose={() => setPreview(null)} />
    </Card>
  );
}
