'use client';

/**
 * The WhatsApp template builder with the Foundryx UIUX switch on. The same
 * builder, the same steps and the same requests (`useTemplateBuilder`); only
 * the page chrome changes:
 * - one red action at the top right: "Submit template" on a draft (full
 *   label names the template), else "Save draft" / "Save and resubmit";
 * - View payload and Save draft as icon actions;
 * - leaving with changes asks "Discard changes to <name>?" (single click);
 * - the preview sits on theme tokens.
 * The "template sent" done page is not built (owner decision).
 */
import { useFxActor } from '../../../components/use-fx-actor';
import { useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import { ChevronLeft, Code2, LoaderCircleIcon } from 'lucide-react';
import { Container } from '@/components/common/container';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog';
import { PageHeader } from '@/components/platform/page-header';
import { FxDiscardDialog } from '@/components/fx/actions/confirm-dialog';
import {
  useRegisterMainAction,
  useRegisterOtherActions,
  type FxMainActionSpec,
  type FxOtherActionSpec,
} from '@/components/fx/actions/page-actions-context';
import { toMetaComponents } from '@/lib/whatsapp-template';
import { channelsListPath } from '../../../components/paths';
import { WaTemplateBuilder } from './wa-template-builder';
import { WaBubblePreview } from './wa-bubble-preview';
import { useTemplateBuilder } from './use-template-builder';
import type { TemplateBuilderViewProps } from './template-builder-view';

export function FxTemplateBuilderView({ channelId, templateId }: TemplateBuilderViewProps) {
  const byWhom = useFxActor();
  const b = useTemplateBuilder({ channelId, templateId, fx: true, byWhom: byWhom });
  const { router, doc, channelPath, dirty, readOnly, identityLocked, canSubmit, saving, submitting } = b;
  // A crumb clicked with unsaved changes waits here for "Discard changes".
  const [pending, setPending] = useState<(() => void) | null>(null);
  const name = doc.name || (templateId ? 'Template' : 'New template');

  const saveLabel = identityLocked ? 'Save and resubmit' : 'Save draft';
  // The header's actions always run the latest handlers (they close over
  // the saved draft's id, which changes after the first save).
  const run = useRef(b);
  run.current = b;
  const onSaveDraft = () => run.current.onSaveDraft();
  const onSubmit = () => run.current.onSubmit();
  const main = useMemo<FxMainActionSpec | null>(() => {
    if (b.loading || b.notFound) return null;
    if (canSubmit) {
      return {
        id: 'submit',
        label: 'Submit template',
        fullLabel: doc.name ? `Submit ${doc.name} to WhatsApp for review` : 'Submit the template to WhatsApp for review',
        onClick: () => void onSubmit(),
        working: submitting,
      };
    }
    if (readOnly) return null;
    return {
      id: 'save',
      label: saveLabel,
      fullLabel: doc.name ? `${saveLabel} for ${doc.name}` : undefined,
      onClick: () => void onSaveDraft(),
      working: saving,
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- handlers read `run`
  }, [b.loading, b.notFound, canSubmit, readOnly, saveLabel, doc.name, saving, submitting]);
  useRegisterMainAction(main);

  const setPayloadOpen = b.setPayloadOpen;
  const others = useMemo<FxOtherActionSpec[]>(() => {
    if (b.loading || b.notFound) return [];
    const list: FxOtherActionSpec[] = [
      {
        id: 'view-payload',
        label: 'View payload',
        icon: <Code2 aria-hidden="true" className="size-[18px]" />,
        onClick: () => setPayloadOpen(true),
      },
    ];
    if (canSubmit && !readOnly) {
      list.push({
        id: 'save-draft',
        label: saveLabel,
        icon: 'save-draft',
        onClick: () => void onSaveDraft(),
        disabledReason: saving || submitting ? 'Saving the template.' : undefined,
      });
    }
    return list;
    // eslint-disable-next-line react-hooks/exhaustive-deps -- handlers read `run`
  }, [b.loading, b.notFound, canSubmit, readOnly, saveLabel, saving, submitting, setPayloadOpen]);
  useRegisterOtherActions(others);

  const guardNav = (proceed: () => void) => {
    if (dirty) setPending(() => proceed);
    else proceed();
  };

  if (b.loading) {
    return (
      <Container width="fluid">
        <div className="flex items-center justify-center py-24 text-(--fx-ink-3)">
          <LoaderCircleIcon aria-label="Loading the template" className="size-6 animate-spin" />
        </div>
      </Container>
    );
  }
  if (b.notFound) {
    return (
      <Container width="fluid">
        <div className="flex flex-col items-center gap-3 py-24 text-center text-(--fx-ink)">
          <p className="font-semibold">This template isn&apos;t here any more.</p>
          <Button asChild variant="fx-text">
            <Link href={channelPath}>Back to the channel</Link>
          </Button>
        </div>
      </Container>
    );
  }

  return (
    <Container width="fluid">
      <div className="flex flex-col gap-4">
        <PageHeader
          title={templateId ? doc.name || 'Template' : 'New template'}
          crumbs={[
            { label: 'Channels', href: channelsListPath },
            { label: 'Channel', href: channelPath },
          ]}
          guardNav={guardNav}
        />
        <Button type="button" variant="fx-text" className="-mt-2 self-start px-0" onClick={b.leave}>
          <ChevronLeft aria-hidden="true" className="size-4" />
          Back to channel
        </Button>

        <div className="flex flex-col gap-4 lg:flex-row">
          <section className="rounded-(--fx-r-l) border border-(--fx-line) bg-(--fx-surface) p-4 text-(--fx-ink) lg:flex-1">
            <WaTemplateBuilder
              channelId={channelId}
              doc={doc}
              onChange={b.setDoc}
              errors={b.errors}
              disabled={readOnly}
              identityLocked={identityLocked}
            />
          </section>
          <div className="lg:w-[380px] lg:shrink-0">
            <div className="lg:sticky lg:top-4">
              <p className="mb-2 text-sm font-semibold text-(--fx-ink-2)">Preview</p>
              <WaBubblePreview doc={doc} />
            </div>
          </div>
        </div>
      </div>

      <Dialog open={b.payloadOpen} onOpenChange={b.setPayloadOpen}>
        <DialogContent className="max-w-2xl rounded-(--fx-r-l) border-(--fx-line) bg-(--fx-surface) p-6 text-(--fx-ink) max-sm:w-[calc(100%-32px)]">
          <DialogTitle className="text-lg font-bold">Payload for {name}</DialogTitle>
          <DialogDescription className="sr-only">The components sent to WhatsApp</DialogDescription>
          <pre className="max-h-[60vh] overflow-auto rounded-(--fx-r-m) bg-(--fx-surface-2) p-3 text-xs">
            {JSON.stringify(toMetaComponents(doc), null, 2)}
          </pre>
        </DialogContent>
      </Dialog>

      <FxDiscardDialog
        open={b.guardOpen || pending !== null}
        name={doc.name || undefined}
        onKeep={() => {
          b.setGuardOpen(false);
          setPending(null);
        }}
        onDiscard={() => {
          const go = pending;
          b.setGuardOpen(false);
          setPending(null);
          if (go) go();
          else router.push(channelPath);
        }}
      />
    </Container>
  );
}
