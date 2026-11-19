'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { toast } from '@/lib/toast';
import { whatsappTemplateService } from '@/services/whatsapp-template-service';
import { validateDoc } from '@/lib/whatsapp-template';
import { ApiError } from '@/lib/api-client';
import type { TemplateStatus, WaTemplateDoc } from '@/types/whatsapp-template';
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

export interface UseTemplateBuilderOptions {
  channelId: string;
  templateId?: string;
  /** Foundryx UIUX switch: only the done toasts' words change. */
  fx?: boolean;
  byWhom?: string;
}

/**
 * The template builder's state, Save draft and Submit, shared by both looks
 * (Foundryx UIUX switch off and on) so the requests cannot drift. Moved out
 * of `template-builder-view.tsx` unchanged except the done toasts' words
 * under the switch.
 */
export function useTemplateBuilder({ channelId, templateId, fx = false, byWhom }: UseTemplateBuilderOptions) {
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
      if (fx) toast.fxDone({ what: `${doc.name} saved as a draft`, byWhom });
      else toast.success('Draft saved.');
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
      if (fx) toast.fxDone({ what: `${doc.name} submitted to WhatsApp for review`, byWhom });
      else toast.success('Submitted for review.');
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

  return {
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
    dirty,
    canSubmit: statusValue === 'LOCAL_DRAFT',
    onSaveDraft,
    onSubmit,
    leave,
  };
}
