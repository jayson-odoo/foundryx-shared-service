'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { zodResolver } from '@hookform/resolvers/zod';
import { useForm, type UseFormReturn } from 'react-hook-form';
import {
  Archive,
  ArchiveRestore,
  ArrowRight,
  ClipboardList,
  FileText,
  GitMerge,
  Lightbulb,
  Rocket,
  Split,
} from 'lucide-react';
import { toast } from '@/lib/toast';
import type { ResourceFormConfig } from '@/components/platform/resource-form';
import type { ResourceAction } from '@/components/platform/resource-list';
import { useCan } from '@/hooks/use-can';
import { useIdeationRuntime } from '@/hooks/use-ideation-runtime';
import type { Idea, Product } from '@/types/ideation';
import type { ListQuery } from '@/types/resource';
import { promoteIdeasToBr } from '../promote-to-br';
import { selectIdeaRows } from '../select-idea-rows';
import { DetailsTab, AttachmentsTab } from './idea-form-fields';
import { IdeaBrsTab } from './idea-brs-tab';
import { IdeaMergedTab } from './idea-merged-tab';
import { ideaFormPath, buildIdeaFormQuery } from './paths';
import { ideaFormSchema, type IdeaFormValues } from './idea-schema';

function toFormValues(idea: Idea | null): IdeaFormValues {
  if (!idea)
    return {
      problem: '',
      productId: '',
      proposedSolution: '',
      impact: '',
      department: '',
      rawText: '',
    };
  return {
    problem: idea.problem,
    productId: idea.productId,
    proposedSolution: idea.proposedSolution ?? '',
    impact: idea.impact ?? '',
    department: idea.department ?? '',
    rawText: idea.rawText,
  };
}

export interface UseIdeaFormResult {
  config: ResourceFormConfig<Idea> | null;
  form: UseFormReturn<IdeaFormValues>;
  isLoading: boolean;
  notFound: boolean;
}

/** Loads the idea + products, wires RHF, and assembles the form config. */
export function useIdeaForm(ideaId: string | undefined, initialEditing: boolean): UseIdeaFormResult {
  const router = useRouter();
  const { service: ideationService, paths, mode } = useIdeationRuntime();
  const { can } = useCan();
  const creating = !ideaId;
  // The Business Requirements tab only makes sense on the OPERATOR surface (the
  // embed iframe has no BR surface) and for a user who can read BRs.
  const showBrsTab =
    mode === 'operator' && can('ideation.business_requirements.read');

  const [idea, setIdea] = useState<Idea | null>(null);
  const [products, setProducts] = useState<Product[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);
  // Bumped whenever a child is split out of this survivor's "Merged from" tab
  // (a `key` on the tab forces `useIdeaMerged` to refetch, mirroring the
  // quick-replace remount pattern used elsewhere in the shell).
  const [mergedReloadToken, setMergedReloadToken] = useState(0);

  const form = useForm<IdeaFormValues>({
    mode: 'onTouched',
    resolver: zodResolver(ideaFormSchema),
    defaultValues: toFormValues(null),
  });

  useEffect(() => {
    ideationService.listProducts().then(setProducts).catch(() => setProducts([]));
  }, [ideationService]);

  useEffect(() => {
    let active = true;
    if (creating) {
      setIdea(null);
      form.reset(toFormValues(null));
      setIsLoading(false);
      return;
    }
    setIsLoading(true);
    ideationService
      .getIdea(ideaId)
      .then((i) => {
        if (!active) return;
        setIdea(i);
        form.reset(toFormValues(i));
        setNotFound(false);
      })
      .catch(() => active && setNotFound(true))
      .finally(() => active && setIsLoading(false));
    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ideaId, creating]);

  // Review fix pattern reused from `use-br-form.tsx` (issue #94, AC-94-36): the
  // pager must re-run the SAME lane the user was actually browsing on the
  // list they came from - carried as an `includeTest` URL param, not
  // re-derived from whichever record happens to be open.
  const searchParams = useSearchParams();
  const includeTestParam = searchParams.get('includeTest');
  const pagerIncludeTest =
    includeTestParam !== null ? includeTestParam === '1' : (idea?.isTest ?? false);

  const fetchRecordAt = useCallback(
    async (query: ListQuery, index: number) => {
      const all = await ideationService.listIdeas({ includeTest: pagerIncludeTest });
      const rows = selectIdeaRows(all, query);
      const row = rows[index];
      return { recordId: row?.id ?? null, total: rows.length };
    },
    [pagerIncludeTest, ideationService],
  );

  // Built directly (not through `paths.formHref`) so the pager's query string
  // is always correct regardless of a runtime's own `formHref` shape; mode
  // still picks the right base path (AC-94-40 - the embed pager stays inside
  // the iframe).
  const buildRecordHref = useCallback(
    (recordId: string, ctx: string, index: number) => {
      const query = buildIdeaFormQuery({ ctx, index, includeTest: pagerIncludeTest });
      return mode === 'embed'
        ? `/embed/ideas/${encodeURIComponent(recordId)}${query}`
        : `${ideaFormPath(recordId)}${query}`;
    },
    [pagerIncludeTest, mode],
  );

  const config = useMemo<ResourceFormConfig<Idea> | null>(() => {
    if (isLoading || notFound) return null;

    // Advancing/restoring fires a status_engine edge by target id (AC-94-53),
    // then refreshes the loaded idea + resets the form baseline.
    const applyStatus = async (id: string, toStatusId: string) => {
      const updated = await ideationService.setStatus(id, toStatusId);
      setIdea(updated);
      form.reset(toFormValues(updated));
    };

    const isMergedChild = Boolean(idea?.mergedIntoId);

    // A merged child is frozen (AC-94-09/26) - the gear offers only Unmerge
    // (split it back out) and Delete. Every lifecycle action lives on the
    // survivor instead.
    const actions: ResourceAction<Idea>[] = isMergedChild
      ? [
          {
            id: 'unmerge',
            label: 'Unmerge',
            icon: Split,
            surfaces: { row: false, form: true, bulk: false },
            run: async (rows) => {
              if (!ideationService.unmerge || !rows[0]) return;
              const [restored] = await ideationService.unmerge(rows[0].id);
              setIdea(restored);
              form.reset(toFormValues(restored));
              toast.success('Idea unmerged.');
            },
          },
          {
            id: 'delete',
            label: 'Delete',
            icon: FileText,
            tone: 'destructive',
            surfaces: { row: false, form: true, bulk: false },
            deferred: { actionKey: 'ideation_ideas.delete', entityType: 'ideation_idea' },
          },
        ]
      : [
          {
            id: 'promote-br',
            label: 'Promote to BR',
            icon: Rocket,
            // The destination is a new draft BR - gated by the BR write perm
            // (hidden in embed, which has no operator user / BR surface).
            permission: 'ideation.business_requirements.manage',
            surfaces: { row: false, form: true, bulk: false },
            // Foolproof-UI: an archived idea can't be promoted.
            isVisible: (rows) => rows.every((r) => !r.statusIsArchived),
            run: async (rows) => {
              // Single current idea → the backend derives the title + pre-fills
              // problem_statement (AC-BI-32b); lands on the new BR's Grill tab.
              await promoteIdeasToBr(rows, router);
            },
          },
          {
            id: 'advance',
            // Label auto-derived from the fireable transition target
            // (status_engine, AC-94-57/52) - e.g. "Move to Triaged".
            label: (rows) => {
              const target = rows[0]?.transitions?.find((t) => t.id === rows[0]?.advanceTransitionId);
              return target ? `Move to ${target.toStatusLabel}` : 'Advance to next stage';
            },
            icon: ArrowRight,
            surfaces: { row: false, form: true, bulk: false },
            isVisible: (rows) => rows.every((r) => !r.statusIsArchived),
            isDisabled: (rows) => rows.some((r) => !r.advanceTransitionId),
            run: async (rows) => {
              const target = rows[0]?.transitions?.find((t) => t.id === rows[0]?.advanceTransitionId);
              if (!target) return;
              await applyStatus(rows[0].id, target.toStatusId);
              toast.success(`Moved to ${target.toStatusLabel}.`);
            },
          },
          {
            id: 'archive',
            label: 'Archive',
            icon: Archive,
            surfaces: { row: false, form: true, bulk: false },
            isVisible: (rows) => rows.every((r) => !r.statusIsArchived),
            // Grace-window deferred action (sprint-4/23, T5 fix round 1, item
            // 15) - no confirm, no `run` (the registered `ideation_ideas.archive`
            // handler commits it server-side; restore stays a plain, un-gated
            // action, so this is the reversible window).
            deferred: { actionKey: 'ideation_ideas.archive', entityType: 'ideation_idea' },
          },
          {
            id: 'restore',
            label: 'Restore',
            icon: ArchiveRestore,
            surfaces: { row: false, form: true, bulk: false },
            isVisible: (rows) => rows.every((r) => r.statusIsArchived),
            isDisabled: (rows) => rows.some((r) => !r.transitions?.length),
            run: async (rows) => {
              const target = rows[0]?.transitions?.[0];
              if (!target) return;
              await applyStatus(rows[0].id, target.toStatusId);
              toast.success('Idea restored.');
            },
          },
          {
            id: 'delete',
            label: 'Delete',
            icon: FileText,
            tone: 'destructive',
            surfaces: { row: false, form: true, bulk: false },
            // Grace-window deferred action - no confirm, no `run`. ResourceForm's
            // own onCommitted already carries the record's ctx/i/from back to
            // the list (AC-DLA-30), matching what this `run` used to do by hand.
            deferred: { actionKey: 'ideation_ideas.delete', entityType: 'ideation_idea' },
          },
        ];

    const onSave = async (): Promise<boolean> => {
      let ok = false;
      await form.handleSubmit(async (values) => {
        if (creating) {
          const created = await ideationService.createIdea({
            productId: values.productId,
            problem: values.problem,
            proposedSolution: values.proposedSolution ?? '',
            impact: values.impact ?? '',
            department: values.department ?? '',
            rawText: values.rawText ?? '',
          });
          toast.success('Idea captured.');
          router.push(paths.formHref(created.id));
        } else {
          // Fields only - a save never moves status (AC-94-34, owner Q5).
          const updated = await ideationService.updateIdea(ideaId, {
            problem: values.problem,
            productId: values.productId,
            proposedSolution: values.proposedSolution ?? '',
            impact: values.impact ?? '',
            department: values.department ?? '',
            rawText: values.rawText ?? '',
          });
          setIdea(updated);
          form.reset(toFormValues(updated));
          toast.success('Idea updated.');
        }
        ok = true;
      })();
      return ok;
    };

    const onCancel = () => {
      if (creating) router.push(paths.listHref);
      else form.reset(toFormValues(idea));
    };

    const onVote = async (target: Idea, dir: 'up' | 'down') => {
      try {
        const updated = await ideationService.vote(target.id, dir);
        setIdea(updated);
      } catch (e) {
        toast.error(e instanceof Error ? e.message : 'Could not vote.');
      }
    };

    // The visible label is the idea's title when set, falling back to the
    // problem text (S1, AC-1106) - a pre-lane idea has no title.
    const visibleLabel = creating ? 'New idea' : (idea?.title ?? idea?.problem ?? 'Idea');

    const mergedCount = idea?.mergedCount ?? 0;

    return {
      breadcrumb:
        mode === 'embed'
          ? [
              { label: 'Ideas', href: paths.listHref },
              { label: visibleLabel },
            ]
          : [
              { label: 'Home', href: '/' },
              { label: 'Ideation', href: paths.listHref },
              { label: 'Ideas', href: paths.listHref },
              { label: visibleLabel },
            ],
      backHref: paths.listHref,
      backLabel: 'Back to ideas',
      title: visibleLabel,
      subtitle: creating
        ? 'Capture a new idea'
        : idea
          ? `${idea.productName} · ${idea.submitterName}${idea.submitterTier ? ` · ${idea.submitterTier}` : ''}`
          : undefined,
      avatar: (
        <span className="flex size-11 items-center justify-center rounded-full bg-primary/10">
          <Lightbulb className="size-5 text-primary" />
        </span>
      ),
      tabs: [
        {
          id: 'details',
          label: 'Details',
          icon: Lightbulb,
          render: ({ editing }: { editing: boolean }) => (
            <DetailsTab
              form={form}
              editing={editing}
              creating={creating}
              idea={idea}
              products={products}
              onVote={onVote}
            />
          ),
        },
        {
          id: 'attachments',
          label: 'Attachments',
          icon: FileText,
          render: () => <AttachmentsTab attachments={idea?.attachments ?? []} />,
        },
        // Business Requirements this idea feeds (reverse lineage, AC-BI-29c) -
        // operator surface only, and only once the idea exists (not on create).
        ...(showBrsTab && !creating && idea
          ? [
              {
                id: 'business-requirements',
                label: 'Business Requirements',
                icon: ClipboardList,
                render: () => <IdeaBrsTab ideaId={idea.id} />,
              },
            ]
          : []),
        // "Merged from" (AC-94-25) - only once this idea is a survivor with at
        // least one merged child.
        ...(!creating && idea && mergedCount > 0
          ? [
              {
                id: 'merged',
                label: 'Merged from',
                icon: GitMerge,
                render: () => (
                  <IdeaMergedTab
                    key={mergedReloadToken}
                    ideaId={idea.id}
                    onUnmerge={async (ids) => {
                      if (!ideationService.unmerge) return;
                      for (const id of ids) await ideationService.unmerge(id);
                      const refreshed = await ideationService.getIdea(idea.id);
                      setIdea(refreshed);
                      setMergedReloadToken((t) => t + 1);
                      toast.success('Idea unmerged.');
                    }}
                  />
                ),
              },
            ]
          : []),
      ],
      actions,
      actionRows: idea ? [idea] : [],
      editable: !creating,
      initialEditing: creating ? true : initialEditing,
      isDirty: form.formState.isDirty,
      onSave,
      onCancel,
      recordNav: creating ? undefined : { fetchAt: fetchRecordAt, buildHref: buildRecordHref },
    };
  }, [
    isLoading,
    notFound,
    creating,
    idea,
    products,
    form,
    initialEditing,
    ideaId,
    router,
    paths,
    mode,
    ideationService,
    showBrsTab,
    mergedReloadToken,
    fetchRecordAt,
    buildRecordHref,
  ]);

  return { config, form, isLoading, notFound };
}
