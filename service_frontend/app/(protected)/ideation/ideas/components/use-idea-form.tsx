'use client';

import { useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { zodResolver } from '@hookform/resolvers/zod';
import { useForm, type UseFormReturn } from 'react-hook-form';
import { Archive, ArchiveRestore, ArrowRight, FileText, Lightbulb } from 'lucide-react';
import { toast } from 'sonner';
import type { ResourceFormConfig } from '@/components/platform/resource-form';
import type { ResourceAction } from '@/components/platform/resource-list';
import { useIdeationRuntime } from '@/hooks/use-ideation-runtime';
import { IDEA_NEXT_STATUS, IDEA_STATUS_LABEL, type Idea, type Product } from '@/types/ideation';
import { DetailsTab, AttachmentsTab } from './idea-form-fields';
import { ideaFormSchema, type IdeaFormValues } from './idea-schema';

function toFormValues(idea: Idea | null): IdeaFormValues {
  if (!idea)
    return {
      problem: '',
      productId: '',
      status: 'captured',
      proposedSolution: '',
      impact: '',
      department: '',
      rawText: '',
    };
  return {
    problem: idea.problem,
    productId: idea.productId,
    status: idea.status,
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
  const creating = !ideaId;

  const [idea, setIdea] = useState<Idea | null>(null);
  const [products, setProducts] = useState<Product[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);

  const form = useForm<IdeaFormValues>({
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

  const config = useMemo<ResourceFormConfig<Idea> | null>(() => {
    if (isLoading || notFound) return null;

    // Advancing/archiving updates status_engine state (prototype: IDEA_NEXT_STATUS),
    // then refreshes the loaded idea + resets the form baseline.
    const applyStatus = async (id: string, status: Idea['status']) => {
      const updated = await ideationService.setStatus(id, status);
      setIdea(updated);
      form.reset(toFormValues(updated));
    };

    const actions: ResourceAction<Idea>[] = [
      {
        id: 'advance',
        // Label auto-derived from the status_engine transition target (prototype:
        // IDEA_NEXT_STATUS) — e.g. "Move to Triaged".
        label: (rows) => {
          const next = rows[0] ? IDEA_NEXT_STATUS[rows[0].status] : undefined;
          return next ? `Move to ${IDEA_STATUS_LABEL[next]}` : 'Advance to next stage';
        },
        icon: ArrowRight,
        surfaces: { row: false, form: true, bulk: false },
        isVisible: (rows) => rows.every((r) => r.status !== 'archived'),
        isDisabled: (rows) => rows.some((r) => !IDEA_NEXT_STATUS[r.status]),
        run: async (rows) => {
          const next = IDEA_NEXT_STATUS[rows[0].status];
          if (!next) return;
          await applyStatus(rows[0].id, next);
          toast.success(`Moved to ${next}.`);
        },
      },
      {
        id: 'archive',
        label: 'Archive',
        icon: Archive,
        surfaces: { row: false, form: true, bulk: false },
        isVisible: (rows) => rows.every((r) => r.status !== 'archived'),
        confirm: {
          title: 'Archive idea',
          description: 'Archived ideas are hidden from the active list but retained. You can restore them later.',
          confirmLabel: 'Archive',
        },
        run: async (rows) => {
          await applyStatus(rows[0].id, 'archived');
          toast.success('Idea archived.');
        },
      },
      {
        id: 'restore',
        label: 'Restore',
        icon: ArchiveRestore,
        surfaces: { row: false, form: true, bulk: false },
        isVisible: (rows) => rows.every((r) => r.status === 'archived'),
        run: async (rows) => {
          await applyStatus(rows[0].id, 'captured');
          toast.success('Idea restored.');
        },
      },
      {
        id: 'delete',
        label: 'Delete',
        icon: FileText,
        tone: 'destructive',
        surfaces: { row: false, form: true, bulk: false },
        confirm: {
          title: 'Delete idea?',
          description: 'This permanently removes the idea from the repository.',
          confirmLabel: 'Delete',
        },
        run: async (rows) => {
          await ideationService.remove(rows[0].id);
          toast.success('Idea deleted.');
          router.push(paths.listHref);
        },
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
          const updated = await ideationService.updateIdea(ideaId, {
            problem: values.problem,
            productId: values.productId,
            proposedSolution: values.proposedSolution ?? '',
            impact: values.impact ?? '',
            department: values.department ?? '',
            rawText: values.rawText ?? '',
            status: values.status,
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

    return {
      breadcrumb:
        mode === 'embed'
          ? [
              { label: 'Ideas', href: paths.listHref },
              { label: creating ? 'New idea' : (idea?.problem ?? 'Idea') },
            ]
          : [
              { label: 'Home', href: '/' },
              { label: 'Ideation', href: paths.listHref },
              { label: 'Ideas', href: paths.listHref },
              { label: creating ? 'New idea' : (idea?.problem ?? 'Idea') },
            ],
      backHref: paths.listHref,
      backLabel: 'Back to ideas',
      title: creating ? 'New idea' : (idea?.problem ?? 'Idea'),
      subtitle: creating
        ? 'Capture a new idea'
        : idea
          ? `${idea.productName} · ${idea.submitterName}`
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
            <DetailsTab form={form} editing={editing} creating={creating} idea={idea} products={products} />
          ),
        },
        {
          id: 'attachments',
          label: 'Attachments',
          icon: FileText,
          render: () => <AttachmentsTab attachments={idea?.attachments ?? []} />,
        },
      ],
      actions,
      actionRows: idea ? [idea] : [],
      editable: !creating,
      initialEditing: creating ? true : initialEditing,
      isDirty: form.formState.isDirty,
      onSave,
      onCancel,
    };
  }, [isLoading, notFound, creating, idea, products, form, initialEditing, ideaId, router, paths, mode, ideationService]);

  return { config, form, isLoading, notFound };
}
