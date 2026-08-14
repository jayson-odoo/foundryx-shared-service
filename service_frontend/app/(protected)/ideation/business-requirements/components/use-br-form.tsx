'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { FileText, GitBranch, History, Lightbulb, MessageSquare, Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import type { ResourceFormConfig } from '@/components/platform/resource-form';
import type { ResourceAction } from '@/components/platform/resource-list';
import { ApiError } from '@/lib/api-client';
import { businessRequirementService } from '@/services/business-requirement-service';
import type { BusinessRequirementDetail } from '@/types/business-requirement';
import type { FormAnswers, FormFieldErrors } from '@/types/forms';
import { BR_PATH, brFormHref } from './paths';
import { BrDetailsTab } from './br-details-tab';
import { BrGrillTab } from './br-grill-tab';
import { BrIdeasTab } from './br-ideas-tab';
import { BrVersionsTab } from './br-versions-tab';
import { BrPlaceholderTab } from './br-placeholder-tab';
import { useBrActions } from './use-br-actions';

interface Detail422 {
  fieldErrors?: Record<string, string>;
  message?: string;
}

function detail422(e: unknown): Detail422 | null {
  if (e instanceof ApiError && e.status === 422 && typeof e.detail === 'object' && e.detail) {
    return e.detail as Detail422;
  }
  return null;
}

export interface UseBrFormResult {
  config: ResourceFormConfig<BusinessRequirementDetail> | null;
  isLoading: boolean;
  notFound: boolean;
}

function answersEqual(a: FormAnswers, b: FormAnswers): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

/**
 * BR detail form config (tabbed ResourceForm). Tabs: Details · Grill · Ideas ·
 * Trace · Versions - but in S2 only Details/Ideas/Versions carry content (Grill =
 * S3, Trace = S4 render empty placeholders). The Details tab renders answers
 * through the form-engine renderer against the BR's STAMPED template doc.
 */
export function useBrForm(
  brId: string,
  initialEditing: boolean,
  initialTab?: string,
): UseBrFormResult {
  const router = useRouter();
  const [br, setBr] = useState<BusinessRequirementDetail | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);

  // Editable state (the form-engine renderer manages its own answer map; RHF is
  // not used here). Dirty = drift vs the loaded record.
  const [title, setTitle] = useState('');
  const [answers, setAnswers] = useState<FormAnswers>({});
  // Server 422 per-field map from a failed save / promote (AC-BI-34b) - rendered
  // inline on the Details tab; cleared when the user edits an answer.
  const [serverFieldErrors, setServerFieldErrors] = useState<FormFieldErrors>({});
  // Bumped by link/unlink on the Ideas tab so the grill re-seeds from fresh
  // source ideas next turn (AC-BI-33) and the Ideas list reloads.
  const [ideasToken, setIdeasToken] = useState(0);

  const onAnswersChange = useCallback((next: FormAnswers) => {
    setAnswers(next);
    // Editing clears the stale server error map (the user is fixing it).
    setServerFieldErrors((prev) => (Object.keys(prev).length ? {} : prev));
  }, []);

  const load = useCallback(async () => {
    setIsLoading(true);
    try {
      const fresh = await businessRequirementService.get(brId);
      setBr(fresh);
      setTitle(fresh.title);
      setAnswers(fresh.answers ?? {});
      setNotFound(false);
    } catch {
      setNotFound(true);
    } finally {
      setIsLoading(false);
    }
  }, [brId]);

  useEffect(() => {
    void load();
  }, [load]);

  const isDirty = useMemo(
    () =>
      br !== null &&
      (title !== br.title || !answersEqual(answers, br.answers ?? {})),
    [answers, br, title],
  );

  const onSave = useCallback(async (): Promise<boolean> => {
    if (!br) return false;
    try {
      const updated = await businessRequirementService.update(brId, {
        title: title.trim(),
        answers,
      });
      setBr(updated);
      setTitle(updated.title);
      setAnswers(updated.answers ?? {});
      setServerFieldErrors({});
      toast.success('Business requirement saved.');
      return true;
    } catch (e) {
      // A 422 (type/format error on a draft save) → inline per-field highlights
      // on the Details tab AND a readable toast - never the raw HTTP status text
      // "Unprocessable Content" (AC-BI-34b). (Required is NOT enforced on save -
      // a draft holds partial answers.)
      const detail = detail422(e);
      if (detail) {
        if (detail.fieldErrors) setServerFieldErrors(detail.fieldErrors);
        toast.error(detail.message ?? 'Some fields need attention before saving.');
        return false;
      }
      toast.error(e instanceof Error ? e.message : 'Save failed.');
      return false;
    }
  }, [answers, br, brId, title]);

  const onCancel = useCallback(() => {
    if (br) {
      setTitle(br.title);
      setAnswers(br.answers ?? {});
    }
  }, [br]);

  // After a grill Generate the BR's answers are freshly persisted - reflect them
  // in the Details tab (the load/setAnswers seam). The BR stays draft (AC-BI-27).
  const onGrillGenerated = useCallback((updated: BusinessRequirementDetail) => {
    setBr(updated);
    setTitle(updated.title);
    setAnswers(updated.answers ?? {});
    toast.success('Requirement generated from the grill.');
  }, []);

  // A lifecycle/promote move refreshed the BR (status, and possibly answers).
  const onBrChanged = useCallback((updated: BusinessRequirementDetail) => {
    setBr(updated);
    setTitle(updated.title);
    setAnswers(updated.answers ?? {});
  }, []);

  // Linking/unlinking an idea mid-session re-seeds the grill's source context
  // next turn (AC-BI-33) - bump the token so the Ideas list + grill state reload.
  const onIdeasChanged = useCallback(() => setIdeasToken((t) => t + 1), []);

  // Graph-driven lifecycle + promote actions (AC-BI-34). The promote edge is
  // gated by the separate .promote permission; a refused promote surfaces inline.
  const lifecycleActions = useBrActions(br, {
    onChanged: onBrChanged,
    onFieldErrors: setServerFieldErrors,
  });

  const config = useMemo<ResourceFormConfig<BusinessRequirementDetail> | null>(() => {
    if (!br) return null;

    const actions: ResourceAction<BusinessRequirementDetail>[] = [
      ...lifecycleActions,
      {
        id: 'delete',
        label: 'Delete',
        icon: Trash2,
        tone: 'destructive',
        surfaces: { form: true },
        confirm: {
          title: 'Delete business requirement',
          description:
            'This permanently removes the BR and its idea links. This action cannot be undone.',
          confirmLabel: 'Delete',
        },
        run: async () => {
          await businessRequirementService.remove(brId);
          toast.success('Business requirement deleted.');
          router.push(BR_PATH);
        },
      },
    ];

    return {
      breadcrumb: [
        { label: 'Business requirements', href: BR_PATH },
        { label: br.title || 'Untitled BR' },
      ],
      backHref: BR_PATH,
      title: br.title || 'Untitled BR',
      subtitle: `${br.statusLabel} · ${br.productName}`,
      tabs: [
        {
          id: 'details',
          label: 'Details',
          icon: FileText,
          render: ({ editing }) => (
            <BrDetailsTab
              editing={editing}
              doc={br.templateDoc}
              answers={answers}
              onAnswersChange={onAnswersChange}
              serverErrors={serverFieldErrors}
            />
          ),
        },
        {
          id: 'grill',
          label: 'Grill',
          icon: MessageSquare,
          render: () => (
            <BrGrillTab
              brId={brId}
              onGenerated={onGrillGenerated}
              hasLinkedIdeas={br.ideaCount > 0}
            />
          ),
        },
        {
          id: 'ideas',
          label: 'Ideas',
          icon: Lightbulb,
          render: () => (
            <BrIdeasTab
              brId={brId}
              productId={br.productId}
              reloadToken={ideasToken}
              onChanged={onIdeasChanged}
            />
          ),
        },
        {
          id: 'trace',
          label: 'Trace',
          icon: GitBranch,
          render: () => <BrPlaceholderTab label="Available after grilling." />,
        },
        {
          id: 'versions',
          label: 'Versions',
          icon: History,
          render: () => <BrVersionsTab brId={brId} />,
        },
      ],
      initialTabId: initialTab ?? 'details',
      actions,
      actionRows: [br],
      editable: true,
      editPermission: 'ideation.business_requirements.manage',
      initialEditing,
      isDirty,
      onSave,
      onCancel,
      recordNav: {
        fetchAt: async (query, index) => {
          const all = await businessRequirementService.list({
            filter: query.statusView === 'trashed' ? 'archived' : 'active',
            search: query.search,
          });
          const row = all[index];
          return { recordId: row?.id ?? null, total: all.length };
        },
        buildHref: (recordId, ctx, index) => brFormHref(recordId, { ctx, index }),
      },
    };
  }, [
    answers,
    br,
    brId,
    ideasToken,
    initialEditing,
    initialTab,
    isDirty,
    lifecycleActions,
    onAnswersChange,
    onCancel,
    onGrillGenerated,
    onIdeasChanged,
    onSave,
    router,
    serverFieldErrors,
  ]);

  return { config, isLoading, notFound };
}
