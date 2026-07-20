'use client';

import { useState } from 'react';
import type { UseFormReturn } from 'react-hook-form';
import {
  ChevronDown,
  ChevronUp,
  FileText,
  Film,
  ImageIcon,
  Mic,
  Paperclip,
} from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from '@/components/ui/card';
import { FormControl, FormField, FormItem, FormMessage } from '@/components/ui/form';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { SearchSelect } from '@/components/platform/search-select';
import { FormRow } from '@/components/platform/resource-form';
import { IdeaAttachmentPreviewDialog } from './idea-attachment-preview-dialog';
import {
  IDEA_SOURCE_LABEL,
  IDEA_STATUS_LABEL,
  type Idea,
  type IdeaAttachment,
  type IdeaAttachmentKind,
  type Product,
} from '@/types/ideation';
import type { IdeaFormValues } from './idea-schema';

const EDITABLE_STATUSES: Idea['status'][] = [
  'captured',
  'triaged',
  'linked',
  'building',
  'delivered',
  'closed',
  'rejected',
];

export interface DetailsTabProps {
  form: UseFormReturn<IdeaFormValues>;
  editing: boolean;
  creating: boolean;
  idea: Idea | null;
  products: Product[];
}

export function DetailsTab({ form, editing, creating, idea, products }: DetailsTabProps) {
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
            <span className="whitespace-pre-wrap">{idea?.problem || '—'}</span>
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
              {idea?.proposedSolution || '—'}
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
              {idea?.impact || '—'}
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
            (idea?.department || '—')
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
            '—'
          )}
        </FormRow>

        <FormRow label="Status">
          {editing && !creating ? (
            <FormField
              control={form.control}
              name="status"
              render={({ field }) => (
                <FormItem className="max-w-sm">
                  <Select value={field.value} onValueChange={field.onChange}>
                    <FormControl>
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      {EDITABLE_STATUSES.map((s) => (
                        <SelectItem key={s} value={s}>
                          {IDEA_STATUS_LABEL[s]}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </FormItem>
              )}
            />
          ) : (
            <Badge variant="outline">{idea ? IDEA_STATUS_LABEL[idea.status] : 'New'}</Badge>
          )}
        </FormRow>

        <FormRow label="Submitter">{idea?.submitterName ?? '—'}</FormRow>

        <FormRow label="Channel">
          {idea ? (
            <Badge variant="outline" appearance="light">
              {IDEA_SOURCE_LABEL[idea.source]}
            </Badge>
          ) : (
            '—'
          )}
        </FormRow>

        <FormRow label="Votes">
          {idea ? (
            <span className="inline-flex items-center gap-3 text-sm">
              <span className="inline-flex items-center gap-0.5">
                <ChevronUp className="size-4 text-emerald-600" />
                {idea.upvotes}
              </span>
              <span className="inline-flex items-center gap-0.5">
                <ChevronDown className="size-4 text-rose-500" />
                {idea.downvotes}
              </span>
            </span>
          ) : (
            '—'
          )}
        </FormRow>

        <FormRow label="Priority">
          {idea ? <span className="tabular-nums">#{idea.priority}</span> : '—'}
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
              {idea?.rawText || '—'}
            </span>
          )}
        </FormRow>

        <FormRow label="Captured">
          {idea ? new Date(idea.createdAt).toLocaleString() : '—'}
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
                  className="flex w-full items-center gap-3 rounded-md px-2 py-1.5 text-left transition-colors hover:bg-muted/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
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
