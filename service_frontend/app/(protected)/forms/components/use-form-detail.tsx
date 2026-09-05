'use client';

/** The form detail config hook (plan sprint-3/01 D18) - tabbed ResourceForm:
 * Builder · Submissions · Flow · Settings · Versions. Clones the workflow
 * form shape: the doc is editor state (dirty rides the shell's guard), the
 * Flow tab's layout draft plugs into the form Save/Cancel (BL-064 final
 * shape), publish runs the validate gate. */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { FileText, GitBranch, History, Inbox, PencilRuler } from 'lucide-react';
import { useForm, type UseFormReturn } from 'react-hook-form';
import { toast } from '@/lib/toast';
import type { ResourceFormConfig } from '@/components/platform/resource-form';
import type { ListQuery } from '@/types/resource';
import type { LayoutController } from '@/components/platform/status-engine';
import { emptyFormDoc } from '@/lib/form-doc';
import { FormPublishError, formService } from '@/services/form-service';
import type { FormDetail, FormDocument } from '@/types/forms';
import { FormBuilderTab } from './form-builder-tab';
import { FormFlowTab } from './form-flow-tab';
import { FormPreviewDialog } from './form-preview-dialog';
import { FormSettingsTab, type FormSettingsValues } from './form-settings-tab';
import { FormSubmissionsTab } from './form-submissions-tab';
import { FormVersionsTab } from './form-versions-tab';
import { FORMS_PATH, formFormHref, formPath } from './paths';
import { useFormActions } from './use-form-actions';

export interface UseFormDetailResult {
  config: ResourceFormConfig<FormDetail> | null;
  form: UseFormReturn<FormSettingsValues>;
  isLoading: boolean;
  notFound: boolean;
}

function settingsValues(record: FormDetail | null): FormSettingsValues {
  return {
    name: record?.name ?? '',
    description: record?.description ?? '',
    access: record?.access ?? 'internal',
    opensAt: record?.opensAt ?? '',
    closesAt: record?.closesAt ?? '',
    maxSubmissions: record?.maxSubmissions != null ? String(record.maxSubmissions) : '',
    submissionLimitPerUser:
      record?.submissionLimitPerUser != null ? String(record.submissionLimitPerUser) : '',
    displayMode: record?.displayMode ?? 'paged',
    pinnedColumns: record?.pinnedColumns ?? [],
    allowRevisions: record?.allowRevisions ?? false,
  };
}

/** `formId === undefined` = create mode (/forms/new). */
export function useFormDetail(
  formId: string | undefined,
  initialEditing: boolean,
  canManage: boolean,
): UseFormDetailResult {
  const router = useRouter();
  const actions = useFormActions();
  const isNew = formId === undefined;

  const [record, setRecord] = useState<FormDetail | null>(null);
  const [doc, setDoc] = useState<FormDocument>(() => emptyFormDoc());
  const docRef = useRef(doc);
  const [docDirty, setDocDirty] = useState(false);
  const [isLoading, setIsLoading] = useState(!isNew);
  const [notFound, setNotFound] = useState(false);
  const [busy, setBusy] = useState(false);
  const [publishProblems, setPublishProblems] = useState<string[]>([]);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [flowDirty, setFlowDirty] = useState(false);
  const layoutController = useRef<LayoutController | null>(null);

  const form = useForm<FormSettingsValues>({ defaultValues: settingsValues(null) });

  useEffect(() => {
    if (isNew) return;
    let cancelled = false;
    setIsLoading(true);
    formService
      .get(formId)
      .then((loaded) => {
        if (cancelled) return;
        if (!loaded) {
          setNotFound(true);
          return;
        }
        setRecord(loaded);
        docRef.current = loaded.draftDefinition;
        setDoc(loaded.draftDefinition);
        form.reset(settingsValues(loaded));
      })
      .finally(() => !cancelled && setIsLoading(false));
    return () => {
      cancelled = true;
    };
  }, [formId, isNew, form]);

  const handleDocChange = useCallback((next: FormDocument) => {
    docRef.current = next;
    setDoc(next);
    setDocDirty(true);
    setPublishProblems([]); // stale problems mislead once the doc moved
  }, []);

  const refresh = useCallback(
    async (id: string) => {
      const fresh = await formService.get(id);
      if (fresh) {
        setRecord(fresh);
        docRef.current = fresh.draftDefinition;
        setDoc(fresh.draftDefinition);
        form.reset(settingsValues(fresh));
        setDocDirty(false);
      }
    },
    [form],
  );

  const onSave = useCallback(async (): Promise<boolean> => {
    const values = form.getValues();
    if (!values.name.trim()) {
      toast.error('Name is required.');
      return false;
    }
    const payload = {
      name: values.name.trim(),
      description: values.description.trim() || null,
      access: values.access,
      draftDefinition: docRef.current,
      opensAt: values.opensAt || null,
      closesAt: values.closesAt || null,
      maxSubmissions: values.maxSubmissions ? Number(values.maxSubmissions) : null,
      submissionLimitPerUser:
        values.access !== 'public' && values.submissionLimitPerUser
          ? Number(values.submissionLimitPerUser)
          : null,
      displayMode: values.displayMode,
      pinnedColumns: values.pinnedColumns,
      allowRevisions: values.allowRevisions,
    };
    try {
      if (isNew) {
        const created = await formService.create({
          name: payload.name,
          description: payload.description ?? undefined,
          access: payload.access,
        });
        await formService.update(created.id, payload);
        toast.success(`Form "${created.name}" created.`);
        router.replace(formPath(created.id));
      } else {
        const updated = await formService.update(formId, payload);
        setRecord(updated);
        form.reset(settingsValues(updated));
        toast.success('Form saved.');
      }
      // The Flow tab's layout draft commits with the same Save (BL-064).
      layoutController.current?.save();
      setDocDirty(false);
      return true;
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Save failed.');
      return false;
    }
  }, [form, isNew, router, formId]);

  const onCancel = useCallback(() => {
    if (isNew) {
      router.push(FORMS_PATH);
      return;
    }
    if (record) {
      docRef.current = record.draftDefinition;
      setDoc(record.draftDefinition);
      form.reset(settingsValues(record));
    }
    layoutController.current?.discard();
    setDocDirty(false);
    setPublishProblems([]);
  }, [form, isNew, router, record]);

  const onPublish = useCallback(async () => {
    if (!formId) return;
    setBusy(true);
    try {
      if (docDirty || form.formState.isDirty) {
        const ok = await onSave();
        if (!ok) return;
      }
      await formService.publish(formId);
      await refresh(formId);
      setPublishProblems([]);
      toast.success('Published - the form can now be filled.');
    } catch (e) {
      if (e instanceof FormPublishError) {
        setPublishProblems(e.problems);
        toast.error('Publish blocked - fix the listed problems.');
      } else {
        toast.error(e instanceof Error ? e.message : 'Publish failed.');
      }
    } finally {
      setBusy(false);
    }
  }, [formId, docDirty, form.formState.isDirty, onSave, refresh]);

  const onUnpublish = useCallback(async () => {
    if (!formId) return;
    setBusy(true);
    try {
      await formService.unpublish(formId);
      await refresh(formId);
      toast.success('Unpublished - the fill link is offline.');
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Unpublish failed.');
    } finally {
      setBusy(false);
    }
  }, [formId, refresh]);

  // Stable across renders (fix round 2, AC-DLA-30/31 D7) - see use-user-form.tsx.
  const fetchRecordAt = useCallback(
    (query: ListQuery, index: number) =>
      formService.getAt(query, index).then((r) => ({
        recordId: r.form?.id ?? null,
        total: r.total,
      })),
    [],
  );
  const buildRecordHref = useCallback(
    (recordId: string, ctx: string, index: number) => formFormHref(recordId, { ctx, index }),
    [],
  );

  const config = useMemo<ResourceFormConfig<FormDetail> | null>(() => {
    if (!isNew && !record) return null;
    return {
      breadcrumb: [
        { label: 'Forms', href: FORMS_PATH },
        { label: isNew ? 'New form' : (record?.name ?? '') },
      ],
      backHref: FORMS_PATH,
      title: isNew ? 'New form' : (record?.name ?? ''),
      subtitle: isNew ? 'Form' : undefined,
      tabs: [
        {
          id: 'builder',
          label: 'Builder',
          icon: PencilRuler,
          render: ({ editing }) => (
            <>
              {record || isNew ? (
                <FormBuilderTab
                  form={
                    record ?? {
                      // Synthetic shell so the toolbar renders in create mode.
                      ...settingsShell(),
                      draftDefinition: doc,
                    }
                  }
                  doc={doc}
                  onDocChange={handleDocChange}
                  editing={editing}
                  canManage={canManage && !isNew}
                  busy={busy}
                  onPreview={() => setPreviewOpen(true)}
                  onPublish={onPublish}
                  onUnpublish={onUnpublish}
                  publishProblems={publishProblems}
                />
              ) : null}
              <FormPreviewDialog
                open={previewOpen}
                onOpenChange={setPreviewOpen}
                name={record?.name ?? form.getValues().name ?? 'Form'}
                definition={doc}
                paged={form.getValues().displayMode === 'paged'}
              />
            </>
          ),
        },
        {
          id: 'submissions',
          label: 'Submissions',
          icon: Inbox,
          render: () =>
            isNew || !record ? (
              <p className="py-12 text-center text-sm text-muted-foreground">
                Save and publish the form to start collecting submissions.
              </p>
            ) : (
              <FormSubmissionsTab form={record} />
            ),
        },
        {
          id: 'flow',
          label: 'Flow',
          icon: GitBranch,
          render: ({ editing }) =>
            isNew || !formId ? (
              <p className="py-12 text-center text-sm text-muted-foreground">
                Save the form to design its submission pipeline.
              </p>
            ) : (
              <FormFlowTab
                formId={formId}
                formName={record?.name ?? ''}
                editing={editing}
                onDirtyChange={setFlowDirty}
                layoutController={layoutController}
              />
            ),
        },
        {
          id: 'settings',
          label: 'Settings',
          icon: FileText,
          render: ({ editing }) => (
            <FormSettingsTab form={form} editing={editing} formRecord={record} doc={doc} />
          ),
        },
        {
          id: 'versions',
          label: 'Versions',
          icon: History,
          render: () =>
            isNew || !formId ? (
              <p className="py-12 text-center text-sm text-muted-foreground">
                Publish the form to create its first version.
              </p>
            ) : (
              <FormVersionsTab formId={formId} currentVersionId={record?.currentVersionId ?? null} />
            ),
        },
      ],
      initialTabId: 'builder',
      actions,
      actionRows: record ? [record] : [],
      editable: true,
      editPermission: 'forms.manage',
      initialEditing: isNew ? true : initialEditing,
      isDirty: docDirty || flowDirty || form.formState.isDirty,
      onSave,
      onCancel,
      onReload: formId ? () => void refresh(formId) : undefined,
      recordNav: isNew
        ? undefined
        : { fetchAt: fetchRecordAt, buildHref: buildRecordHref },
    };
  }, [
    actions,
    busy,
    canManage,
    doc,
    docDirty,
    flowDirty,
    form,
    formId,
    handleDocChange,
    initialEditing,
    isNew,
    onCancel,
    onPublish,
    onSave,
    onUnpublish,
    previewOpen,
    publishProblems,
    record,
    refresh,
    fetchRecordAt,
    buildRecordHref,
  ]);

  return { config, form, isLoading, notFound };
}

/** Blank FormDetail shell for create mode (toolbar needs a record shape). */
function settingsShell(): Omit<FormDetail, 'draftDefinition'> {
  return {
    id: '',
    name: '',
    slug: '',
    description: null,
    status: 'draft',
    access: 'internal',
    isTrashed: false,
    currentVersionId: null,
    currentVersionNumber: null,
    hasUnpublishedChanges: true,
    opensAt: null,
    closesAt: null,
    maxSubmissions: null,
    submissionLimitPerUser: null,
    pinnedColumns: [],
    displayMode: 'paged',
    allowRevisions: false,
    submissionCount: 0,
    createdAt: '',
    updatedAt: '',
  };
}
