'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { ArrowLeft, Loader2, Save, Send, Code2, LoaderCircleIcon } from 'lucide-react';
import { toast } from 'sonner';
import { Container } from '@/components/common/container';
import { Button } from '@/components/ui/button';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Card, CardContent } from '@/components/ui/card';
import { whatsappTemplateService } from '@/services/whatsapp-template-service';
import { toMetaComponents, validateDoc } from '@/lib/whatsapp-template';
import { ApiError } from '@/lib/api-client';
import type { TemplateStatus, WaTemplateDoc } from '@/types/whatsapp-template';
import { WaTemplateBuilder } from './wa-template-builder';
import { WaBubblePreview } from './wa-bubble-preview';
import { channelFormPath } from '../../../components/paths';

const BLANK: WaTemplateDoc = {
  name: '',
  category: 'UTILITY',
  language: 'en_US',
  header: null,
  body: { text: '', examples: [] },
  footer: null,
  buttons: null,
};

const READONLY_STATUSES: TemplateStatus[] = ['PENDING', 'DISABLED'];
const COMPONENTS_ONLY: TemplateStatus[] = ['APPROVED', 'REJECTED', 'PAUSED'];

export interface TemplateBuilderViewProps {
  channelId: string;
  templateId?: string;
}

export function TemplateBuilderView({ channelId, templateId }: TemplateBuilderViewProps) {
  const router = useRouter();
  const [doc, setDoc] = useState<WaTemplateDoc>(BLANK);
  const [baseline, setBaseline] = useState<string>(JSON.stringify(BLANK));
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [statusValue, setStatusValue] = useState<TemplateStatus>('LOCAL_DRAFT');
  const [loading, setLoading] = useState<boolean>(Boolean(templateId));
  const [notFound, setNotFound] = useState(false);
  const [saving, setSaving] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [payloadOpen, setPayloadOpen] = useState(false);
  const [guardOpen, setGuardOpen] = useState(false);
  // Once a brand-new draft is saved, remember its id so a follow-up action
  // (Submit right after Save) edits it instead of creating a duplicate before
  // the route param propagates.
  const [savedId, setSavedId] = useState<string | undefined>(templateId);

  const channelPath = channelFormPath(channelId);

  useEffect(() => {
    if (!templateId) return;
    let active = true;
    setLoading(true);
    whatsappTemplateService
      .get(channelId, templateId)
      .then((d) => {
        if (!active) return;
        setDoc(d.doc);
        setBaseline(JSON.stringify(d.doc));
        setStatusValue(d.status);
        setNotFound(false);
      })
      .catch(() => active && setNotFound(true))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [channelId, templateId]);

  const readOnly = READONLY_STATUSES.includes(statusValue);
  const identityLocked = COMPONENTS_ONLY.includes(statusValue);
  const dirty = JSON.stringify(doc) !== baseline;

  const persist = async (): Promise<string | null> => {
    const clientErrors = validateDoc(doc);
    if (Object.keys(clientErrors).length) {
      setErrors(clientErrors);
      toast.error('Please fix the highlighted fields.');
      return null;
    }
    setErrors({});
    try {
      const existingId = templateId ?? savedId;
      const saved = existingId
        ? await whatsappTemplateService.edit(channelId, existingId, doc)
        : await whatsappTemplateService.saveDraft(channelId, doc);
      setBaseline(JSON.stringify(saved.doc));
      setStatusValue(saved.status);
      setSavedId(saved.id);
      return saved.id;
    } catch (err) {
      if (err instanceof ApiError && err.status === 422) {
        const fieldErrors = (err.detail as { fieldErrors?: Record<string, string> } | undefined)?.fieldErrors;
        if (fieldErrors) {
          setErrors(fieldErrors);
          toast.error('Please fix the highlighted fields.');
          return null;
        }
      }
      toast.error('Could not save. Your input is kept - please retry.');
      return null;
    }
  };

  const onSaveDraft = async () => {
    setSaving(true);
    const id = await persist();
    setSaving(false);
    if (id) {
      toast.success('Draft saved.');
      router.replace(`${channelPath}/templates/${id}`);
    }
  };

  const onSubmit = async () => {
    setSubmitting(true);
    const id = await persist();
    if (!id) {
      setSubmitting(false);
      return;
    }
    try {
      await whatsappTemplateService.submit(channelId, id);
      toast.success('Submitted for review.');
      router.push(channelPath);
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : 'Submit failed.';
      toast.error(`${msg} Your draft is saved - please retry.`);
      router.replace(`${channelPath}/templates/${id}`);
    } finally {
      setSubmitting(false);
    }
  };

  const leave = () => {
    if (dirty) setGuardOpen(true);
    else router.push(channelPath);
  };

  if (loading) {
    return (
      <Container width="fluid">
        <div className="flex items-center justify-center py-24 text-muted-foreground">
          <LoaderCircleIcon className="size-6 animate-spin" />
        </div>
      </Container>
    );
  }
  if (notFound) {
    return (
      <Container width="fluid">
        <div className="flex flex-col items-center gap-3 py-24 text-center">
          <p className="text-sm font-medium">Template not found.</p>
          <Button variant="outline" size="sm" asChild>
            <Link href={channelPath}>Back to channel</Link>
          </Button>
        </div>
      </Container>
    );
  }

  const canSubmit = statusValue === 'LOCAL_DRAFT';

  return (
    <Container width="fluid">
      <div className="flex flex-col gap-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <Button variant="ghost" size="sm" onClick={leave}>
            <ArrowLeft className="size-4" /> Back to channel
          </Button>
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="outline" size="sm" onClick={() => setPayloadOpen(true)}>
              <Code2 className="size-4" /> View payload
            </Button>
            {!readOnly && (
              <Button variant="outline" size="sm" onClick={onSaveDraft} disabled={saving || submitting}>
                {saving ? <Loader2 className="size-4 animate-spin" /> : <Save className="size-4" />}
                {identityLocked ? 'Save & resubmit' : 'Save draft'}
              </Button>
            )}
            {canSubmit && (
              <Button size="sm" onClick={onSubmit} disabled={saving || submitting}>
                {submitting ? <Loader2 className="size-4 animate-spin" /> : <Send className="size-4" />}
                Submit
              </Button>
            )}
          </div>
        </div>

        <h1 className="font-heading text-xl font-semibold">
          {templateId ? doc.name || 'Template' : 'New template'}
        </h1>

        <div className="flex flex-col gap-4 lg:flex-row">
          <Card className="lg:flex-1">
            <CardContent className="py-4">
              <WaTemplateBuilder
                channelId={channelId}
                doc={doc}
                onChange={setDoc}
                errors={errors}
                disabled={readOnly}
                identityLocked={identityLocked}
              />
            </CardContent>
          </Card>
          <div className="lg:w-[380px] lg:shrink-0">
            <div className="lg:sticky lg:top-4">
              <p className="mb-2 text-sm font-medium text-muted-foreground">Preview</p>
              <WaBubblePreview doc={doc} />
            </div>
          </div>
        </div>
      </div>

      <Dialog open={payloadOpen} onOpenChange={setPayloadOpen}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>Template payload</DialogTitle>
          </DialogHeader>
          <pre className="max-h-[60vh] overflow-auto rounded-md bg-muted p-3 text-xs">
            {JSON.stringify(toMetaComponents(doc), null, 2)}
          </pre>
        </DialogContent>
      </Dialog>

      <AlertDialog open={guardOpen} onOpenChange={setGuardOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Discard changes?</AlertDialogTitle>
            <AlertDialogDescription>
              You have unsaved changes. Leaving will discard them.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={() => router.push(channelPath)}>Discard</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Container>
  );
}
