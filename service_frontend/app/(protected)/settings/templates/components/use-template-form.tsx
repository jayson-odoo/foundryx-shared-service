'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { LayoutTemplate, Settings2 } from 'lucide-react';
import { useForm, type UseFormReturn } from 'react-hook-form';
import { toast } from 'sonner';
import type { ResourceFormConfig } from '@/components/platform/resource-form';
import { EmailEditor } from '@/components/platform/email-editor';
import { CanvasEditor } from '@/components/platform/canvas-editor';
import { createBlankDocument, createBlankDocumentDoc } from '@/lib/template-doc';
import { createBlankBadgeDoc } from '@/lib/canvas-doc';
import { ruleEngineService } from '@/services/rule-engine-service';
import { templateEngineService } from '@/services/template-service';
import type { RuleFact } from '@/types/rules';
import {
  isCanvasDoc,
  type AnyTemplateDoc,
  type CanvasDocument,
  type Template,
  type TemplateContext,
  type TemplateDocument,
  type TemplateType,
} from '@/types/templates';

/** Blank doc for a freshly-chosen surface type (create flow). */
function blankDocForType(type: TemplateType): AnyTemplateDoc {
  if (type === 'badge') return createBlankBadgeDoc();
  if (type === 'document') return createBlankDocumentDoc();
  return createBlankDocument();
}
import { TEMPLATES_PATH, templateFormHref, templatePath } from './paths';
import { useTemplateActions } from './use-template-actions';
import { TemplateSettingsFields } from './template-settings-fields';

export interface TemplateFormValues {
  name: string;
  subject: string;
  context: string;
  /** Surface type - editable in CREATE mode only (immutable after). */
  type: TemplateType;
}

export interface UseTemplateFormResult {
  config: ResourceFormConfig<Template> | null;
  form: UseFormReturn<TemplateFormValues>;
  isLoading: boolean;
  notFound: boolean;
}

/** `templateId === undefined` = create mode (/settings/templates/new). */
export function useTemplateForm(
  templateId: string | undefined,
  initialEditing: boolean,
): UseTemplateFormResult {
  const router = useRouter();
  const actions = useTemplateActions();
  const isNew = templateId === undefined;

  const [template, setTemplate] = useState<Template | null>(null);
  const [contexts, setContexts] = useState<TemplateContext[]>([]);
  const [visibilityFacts, setVisibilityFacts] = useState<RuleFact[]>([]);
  const [doc, setDoc] = useState<AnyTemplateDoc>(() => createBlankDocument());
  const [docDirty, setDocDirty] = useState(false);
  // Freshest doc for onSave: clicking Save blurs an inline editor first -
  // its commit lands in state AFTER the closure the click handler captured.
  const docRef = useRef(doc);
  const [isLoading, setIsLoading] = useState(!isNew);
  const [notFound, setNotFound] = useState(false);

  const form = useForm<TemplateFormValues>({
    defaultValues: { name: '', subject: '', context: '', type: 'email' },
  });

  // Load contexts (both modes) + the template (edit mode).
  useEffect(() => {
    let cancelled = false;
    templateEngineService.listContexts().then((rows) => {
      if (!cancelled) setContexts(rows);
    });
    if (!isNew) {
      setIsLoading(true);
      templateEngineService.getTemplate(templateId).then((loaded) => {
        if (cancelled) return;
        if (!loaded) {
          setNotFound(true);
        } else {
          setTemplate(loaded);
          docRef.current = loaded.doc;
          setDoc(loaded.doc);
          form.reset({
            name: loaded.name,
            subject: loaded.subject,
            context: loaded.context,
            type: loaded.type,
          });
        }
        setIsLoading(false);
      });
    }
    return () => {
      cancelled = true;
    };
  }, [templateId, isNew, form]);

  // Visibility facts follow the selected context's fact sources (D8).
  const contextKey = form.watch('context');
  const activeContext = useMemo(
    () => contexts.find((c) => c.key === contextKey) ?? null,
    [contexts, contextKey],
  );

  useEffect(() => {
    let cancelled = false;
    if (activeContext?.factSources.length) {
      ruleEngineService.getFacts(activeContext.factSources).then((facts) => {
        if (!cancelled) setVisibilityFacts(facts);
      });
    } else {
      setVisibilityFacts([]);
    }
    return () => {
      cancelled = true;
    };
  }, [activeContext]);

  // Create mode: picking a surface type re-seeds the blank doc + clears the
  // context (the fact vocabulary is per-surface). No-op in edit mode (type is
  // immutable once created).
  const typeKey = form.watch('type');
  useEffect(() => {
    if (!isNew) return;
    const blank = blankDocForType(typeKey);
    docRef.current = blank;
    setDoc(blank);
    if (form.getValues('context')) form.setValue('context', '');
  }, [typeKey, isNew, form]);

  const handleDocChange = useCallback((next: AnyTemplateDoc) => {
    docRef.current = next; // sync BEFORE the state flush - Save reads this
    setDoc(next);
    setDocDirty(true);
  }, []);

  const renderCanvasHtml = useCallback(
    (current: CanvasDocument) =>
      templateEngineService.previewCanvasHtml({
        id: isNew ? undefined : templateId,
        doc: current,
        context: form.getValues('context'),
      }),
    [form, isNew, templateId],
  );

  const renderCanvasPdf = useCallback(
    (current: CanvasDocument) =>
      templateEngineService.previewCanvasPdf({
        id: isNew ? undefined : templateId,
        doc: current,
        context: form.getValues('context'),
      }),
    [form, isNew, templateId],
  );

  const renderPreview = useCallback(
    (current: TemplateDocument) =>
      templateEngineService.preview(current, form.getValues('context'), form.getValues('subject')),
    [form],
  );

  const renderPdf = useCallback(
    (current: TemplateDocument) =>
      templateEngineService.previewDocumentPdf({
        id: isNew ? undefined : templateId,
        doc: current,
        context: form.getValues('context'),
        subject: form.getValues('subject'),
      }),
    [form, isNew, templateId],
  );

  const renderDocHtml = useCallback(
    (current: TemplateDocument) =>
      templateEngineService.previewDocumentHtml({
        id: isNew ? undefined : templateId,
        doc: current,
        context: form.getValues('context'),
        subject: form.getValues('subject'),
      }),
    [form, isNew, templateId],
  );

  const onSave = useCallback(async (): Promise<boolean> => {
    const values = form.getValues();
    if (!values.name.trim()) {
      toast.error('Name is required.');
      return false;
    }
    if (!values.context) {
      toast.error('Pick a context - it defines the available merge fields.');
      return false;
    }
    const input = {
      name: values.name.trim(),
      subject: values.subject,
      context: values.context,
      doc: docRef.current,
      // type rides on create only (immutable after); backend defaults to email.
      ...(isNew ? { type: values.type } : {}),
    };
    try {
      if (isNew) {
        const created = await templateEngineService.createTemplate(input);
        toast.success(`Template "${created.name}" created.`);
        router.replace(templatePath(created.id));
      } else {
        const updated = await templateEngineService.updateTemplate(templateId, input);
        setTemplate(updated);
        form.reset({ name: updated.name, subject: updated.subject, context: updated.context });
        toast.success('Template saved.');
        if (updated.id !== templateId) {
          // First edit of a platform default FORKED a tenant copy (D6) -
          // follow the fork or the URL would reload the platform row.
          router.replace(templatePath(updated.id));
        }
      }
      setDocDirty(false);
      return true;
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Save failed.');
      return false;
    }
  }, [form, isNew, router, templateId]);

  const onCancel = useCallback(() => {
    if (isNew) {
      router.push(TEMPLATES_PATH);
      return;
    }
    if (template) {
      docRef.current = template.doc;
      setDoc(template.doc);
      form.reset({ name: template.name, subject: template.subject, context: template.context });
    }
    setDocDirty(false);
  }, [form, isNew, router, template]);

  const config = useMemo<ResourceFormConfig<Template> | null>(() => {
    if (!isNew && !template) return null;
    const mergeFields = activeContext?.facts ?? [];
    const listFacts = activeContext?.listFacts ?? [];
    const surfaceType: TemplateType = isNew ? typeKey : (template?.type ?? 'email');
    const isBadge = surfaceType === 'badge';
    const surface = surfaceType === 'document' ? 'document' : 'email';
    return {
      breadcrumb: [
        { label: 'Settings' },
        { label: 'Templates', href: TEMPLATES_PATH },
        { label: isNew ? 'New template' : (template?.name ?? '') },
      ],
      backHref: TEMPLATES_PATH,
      title: isNew ? 'New template' : (template?.name ?? ''),
      subtitle: isNew
        ? `${surfaceType === 'badge' ? 'Badge / canvas' : surfaceType === 'document' ? 'Document (PDF)' : 'Email'} template`
        : template?.key,
      tabs: [
        {
          id: 'settings',
          label: 'Settings',
          icon: Settings2,
          render: ({ editing }) => (
            <TemplateSettingsFields
              form={form}
              editing={editing}
              isNew={isNew}
              template={template}
              contexts={contexts}
              mergeFields={mergeFields}
            />
          ),
        },
        {
          id: 'design',
          label: 'Design',
          icon: LayoutTemplate,
          render: ({ editing }) =>
            isBadge && isCanvasDoc(doc) ? (
              <CanvasEditor
                doc={doc}
                onChange={handleDocChange}
                editing={editing}
                mergeFields={mergeFields}
                visibilityFacts={visibilityFacts}
                renderCanvasHtml={renderCanvasHtml}
                renderCanvasPdf={renderCanvasPdf}
              />
            ) : (
              !isCanvasDoc(doc) && (
                <EmailEditor
                  doc={doc}
                  onChange={handleDocChange}
                  editing={editing}
                  surface={surface}
                  listFacts={listFacts}
                  mergeFields={mergeFields}
                  visibilityFacts={visibilityFacts}
                  renderPreview={renderPreview}
                  renderDocHtml={renderDocHtml}
                  renderPdf={renderPdf}
                />
              )
            ),
        },
      ],
      initialTabId: 'design',
      actions,
      actionRows: template ? [template] : [],
      editable: true,
      editPermission: 'templates.manage',
      initialEditing: isNew ? true : initialEditing,
      isDirty: docDirty || form.formState.isDirty,
      onSave,
      onCancel,
      // House Form invariant: circular N / M prev-next record-nav (?ctx=&i=).
      recordNav: isNew
        ? undefined
        : {
            fetchAt: (query, index) =>
              templateEngineService.getAt(query, index).then((r) => ({
                recordId: r.template?.id ?? null,
                total: r.total,
              })),
            buildHref: (recordId, ctx, index) => templateFormHref(recordId, { ctx, index }),
          },
    };
  }, [
    actions,
    activeContext,
    contexts,
    doc,
    docDirty,
    form,
    handleDocChange,
    initialEditing,
    isNew,
    onCancel,
    onSave,
    renderCanvasHtml,
    renderCanvasPdf,
    renderDocHtml,
    renderPdf,
    renderPreview,
    template,
    typeKey,
    visibilityFacts,
  ]);

  return { config, form, isLoading, notFound };
}
