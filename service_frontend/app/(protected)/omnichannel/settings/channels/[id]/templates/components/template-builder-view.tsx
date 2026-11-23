'use client';

import Link from 'next/link';
import { ArrowLeft, Loader2, Save, Send, Code2, LoaderCircleIcon } from 'lucide-react';
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
import { toMetaComponents } from '@/lib/whatsapp-template';
import { useFx } from '@/hooks/use-fx';
import { WaTemplateBuilder } from './wa-template-builder';
import { WaBubblePreview } from './wa-bubble-preview';
import { useTemplateBuilder } from './use-template-builder';
import { FxTemplateBuilderView } from './fx-template-builder-view';

export interface TemplateBuilderViewProps {
  channelId: string;
  templateId?: string;
}

export function TemplateBuilderView(props: TemplateBuilderViewProps) {
  return useFx() ? <FxTemplateBuilderView {...props} /> : <TemplateBuilderViewLegacy {...props} />;
}

function TemplateBuilderViewLegacy({ channelId, templateId }: TemplateBuilderViewProps) {
  const {
    router,
    doc,
    setDoc,
    errors,
    statusValue,
    loading,
    notFound,
    saving,
    submitting,
    payloadOpen,
    setPayloadOpen,
    guardOpen,
    setGuardOpen,
    channelPath,
    readOnly,
    identityLocked,
    onSaveDraft,
    onSubmit,
    leave,
  } = useTemplateBuilder({ channelId, templateId });

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
                Submit template
              </Button>
            )}
          </div>
        </div>

        <h2 className="font-heading text-xl font-semibold">
          {templateId ? doc.name || 'Template' : 'New template'}
        </h2>

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
