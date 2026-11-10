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
  Plus,
  X,
} from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
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
        <FormRow label="Title">
          {editing ? (
            <FormField
              control={form.control}
              name="title"
              render={({ field }) => (
                <FormItem className="max-w-xl">
                  <FormControl>
                    <Input placeholder="A short name for the idea" {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
          ) : (
            <span>{idea?.title || '-'}</span>
          )}
        </FormRow>

        <TextRow form={form} editing={editing} name="problem" label="Business problem" required placeholder="What problem does the business have?" value={idea?.problem} />
        <TextRow form={form} editing={editing} name="desiredOutcome" label="Desired outcome" placeholder="What should be true once it is solved?" value={idea?.desiredOutcome} />

        <FormRow label="Use cases">
          {editing ? (
            <FormField
              control={form.control}
              name="useCases"
              render={({ field }) => (
                <FormItem className="max-w-xl">
                  <FormControl>
                    <UseCasesInput value={field.value} onChange={field.onChange} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
          ) : idea?.useCases && idea.useCases.length > 0 ? (
            <ul className="list-disc space-y-0.5 pl-5">
              {idea.useCases.map((u, i) => (
                <li key={`${i}-${u}`} className="whitespace-pre-wrap">
                  {u}
                </li>
              ))}
            </ul>
          ) : (
            '-'
          )}
        </FormRow>

        <TextRow form={form} editing={editing} name="currentWorkaround" label="Current workaround" placeholder="How is it handled today?" value={idea?.currentWorkaround} />

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

        <FormRow label="Original message">
          {editing ? (
            <FormField
              control={form.control}
              name="rawText"
              render={({ field }) => (
                <FormItem className="max-w-xl">
                  <FormControl>
                    <Textarea rows={4} placeholder="The message as it was sent" {...field} />
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

type CardTextField = 'problem' | 'desiredOutcome' | 'currentWorkaround';

interface TextRowProps {
  form: UseFormReturn<IdeaFormValues>;
  editing: boolean;
  name: CardTextField;
  label: string;
  placeholder: string;
  value?: string | null;
  required?: boolean;
}

/** One multi-line card field: a Textarea in edit mode, the text otherwise. */
function TextRow({ form, editing, name, label, placeholder, value, required }: TextRowProps) {
  return (
    <FormRow label={label} required={required && editing}>
      {editing ? (
        <FormField
          control={form.control}
          name={name}
          render={({ field }) => (
            <FormItem className="max-w-xl">
              <FormControl>
                <Textarea rows={3} placeholder={placeholder} {...field} />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
      ) : (
        <span className="whitespace-pre-wrap">{value || '-'}</span>
      )}
    </FormRow>
  );
}

export interface UseCasesInputProps {
  value: string[];
  onChange: (value: string[]) => void;
}

/** Use cases editor (plan 20, AC-20-07): one Input per use case with remove,
 * plus an add button. Blank rows are dropped on save. */
export function UseCasesInput({ value, onChange }: UseCasesInputProps) {
  const items = value.length > 0 ? value : [''];
  const update = (index: number, next: string) =>
    onChange(items.map((item, i) => (i === index ? next : item)));
  const removeAt = (index: number) => onChange(items.filter((_, i) => i !== index));
  return (
    <div className="flex flex-col gap-2">
      {items.map((item, index) => (
        <div key={index} className="flex items-center gap-2">
          <Input
            value={item}
            onChange={(e) => update(index, e.target.value)}
            placeholder="A situation where this is needed"
            aria-label={`Use case ${index + 1}`}
          />
          <Button
            type="button"
            variant="ghost"
            mode="icon"
            size="sm"
            onClick={() => removeAt(index)}
            aria-label={`Remove use case ${index + 1}`}
            disabled={items.length === 1 && !item}
          >
            <X />
          </Button>
        </div>
      ))}
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="self-start"
        onClick={() => onChange([...items, ''])}
      >
        <Plus /> Add use case
      </Button>
    </div>
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
                    {a.fromIdea && (
                      <Badge variant="outline" appearance="light" size="sm">
                        from {a.fromIdea.ideaNumber ?? 'merged idea'}
                      </Badge>
                    )}
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
