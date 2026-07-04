'use client';

/**
 * Review-process detail (AC-06-38) — Details + Roles on the full-page Resource
 * form (read-by-default + global Edit toggle, dirty-guard). The picker universes
 * (status mapping, score field, RULE facts) re-fetch from the selected forms via
 * `useReviewConfigMeta` (AC-06-55); PERSONA/profile sources only show when the
 * `ems` module is active (foolproof-UI). Reuses RuleBuilder/MultiSelect/
 * SearchSelect — no parallel components.
 */
import { useEffect, useMemo, useState } from 'react';
import { useForm } from 'react-hook-form';
import { ClipboardList, Info, LoaderCircleIcon, Users } from 'lucide-react';
import { toast } from 'sonner';
import { Container } from '@/components/common/container';
import { Form } from '@/components/ui/form';
import { ResourceForm } from '@/components/platform/resource-form';
import type { ResourceFormConfig } from '@/components/platform/resource-form/types';
import type { SearchSelectOption } from '@/components/platform/search-select';
import { useInstalledModules } from '@/hooks/use-app-store';
import { useReviewActorOptions } from '@/hooks/use-review-actor-options';
import {
  useReviewConfig,
  useReviewConfigMeta,
  useReviewSubmissions,
} from '@/hooks/use-review-configs';
import { formService } from '@/services/form-service';
import { reviewConfigService } from '@/services/review-config-service';
import type { ReviewConfig, ReviewConfigUpdateInput, ReviewRoleInput } from '@/types/review';
import { DetailsTab, type DetailsValues } from './details-tab';
import { RolesTab } from './roles-tab';
import { SubmissionsTab } from './submissions-tab';

function valuesFromConfig(c: ReviewConfig): DetailsValues {
  return {
    name: c.name,
    formId: c.formId,
    reviewFormId: c.reviewFormId,
    requiredReviewCount: c.requiredReviewCount,
    scoreFieldKey: c.scoreFieldKey,
    windowStart: c.windowStart,
    windowEnd: c.windowEnd,
    reviewStartStatusId: c.reviewStartStatusId,
    revisionsStatusId: c.revisionsStatusId,
    acceptedStatusId: c.acceptedStatusId,
    rejectedStatusId: c.rejectedStatusId,
    isActive: c.isActive,
  };
}

function rolesFromConfig(c: ReviewConfig): ReviewRoleInput[] {
  return c.roles.map((r) => ({
    key: r.key,
    label: r.label,
    canSubmit: r.canSubmit,
    canReview: r.canReview,
    canDecide: r.canDecide,
    actorSource: r.actorSource,
    actorIdentityKind: r.actorIdentityKind,
    boundPersonaId: r.boundPersonaId,
    boundStaffRoleId: r.boundStaffRoleId,
    conditionsJson: r.conditionsJson,
    sortOrder: r.sortOrder,
    actors: r.actors.map((a) => ({
      actorKind: a.actorKind,
      actorId: a.actorId,
      conditionsJson: a.conditionsJson,
      sortOrder: a.sortOrder,
    })),
  }));
}

export function ReviewConfigDetail({ id }: { id: string }) {
  const { config, loading, error, reload } = useReviewConfig(id);
  const { isActive } = useInstalledModules();
  const emsActive = isActive('ems');

  // RHF drives only the dirty-guard; the actual field state lives in `values`
  // (the shell's Form context needs a useForm, but we manage values manually so
  // the picker resets on form-id change are explicit).
  const form = useForm<DetailsValues>();
  const [values, setValues] = useState<DetailsValues | null>(null);
  const [roles, setRoles] = useState<ReviewRoleInput[]>([]);
  const [dirty, setDirty] = useState(false);
  const [formOptions, setFormOptions] = useState<SearchSelectOption[]>([]);

  const meta = useReviewConfigMeta(values?.formId ?? null, values?.reviewFormId ?? null);
  const actorOptions = useReviewActorOptions(emsActive);
  const submissions = useReviewSubmissions(config ? id : null);

  useEffect(() => {
    formService
      .list({ page: 0, pageSize: 200 }) // /forms caps page_size at 200 — >200 → 422
      .then((r) => setFormOptions(r.data.map((f) => ({ value: f.id, label: f.name }))))
      .catch(() => setFormOptions([]));
  }, []);

  useEffect(() => {
    if (config) {
      setValues(valuesFromConfig(config));
      setRoles(rolesFromConfig(config));
      setDirty(false);
      form.reset(valuesFromConfig(config));
    }
  }, [config, form]);

  const setDetails = (next: Partial<DetailsValues>) => {
    setValues((v) => (v ? { ...v, ...next } : v));
    setDirty(true);
  };
  const setRolesState = (next: ReviewRoleInput[]) => {
    setRoles(next);
    setDirty(true);
  };

  const resetToConfig = () => {
    if (config) {
      setValues(valuesFromConfig(config));
      setRoles(rolesFromConfig(config));
      setDirty(false);
    }
  };

  const cfgConfig = useMemo<ResourceFormConfig<ReviewConfig> | null>(() => {
    if (!config || !values) return null;
    return {
      breadcrumb: [{ label: 'Review processes', href: '/reviews' }, { label: config.name }],
      backHref: '/reviews',
      backLabel: 'Review processes',
      title: config.name,
      subtitle: 'Review and approval over a form submission',
      tabs: [
        {
          id: 'details',
          label: 'Details',
          icon: Info,
          render: ({ editing }) => (
            <DetailsTab
              values={values}
              onChange={setDetails}
              editing={editing}
              meta={meta.meta}
              formOptions={formOptions}
            />
          ),
        },
        {
          id: 'roles',
          label: 'Roles',
          icon: Users,
          render: ({ editing }) => (
            <RolesTab
              roles={roles}
              onChange={setRolesState}
              editing={editing}
              emsActive={emsActive}
              facts={meta.meta.submissionFacts}
              actorOptions={actorOptions}
            />
          ),
        },
        {
          id: 'submissions',
          label: 'Submissions',
          icon: ClipboardList,
          render: () => (
            <SubmissionsTab
              submissions={submissions.submissions}
              loading={submissions.loading}
              error={submissions.error}
            />
          ),
        },
      ],
      actions: [],
      actionRows: [config],
      editable: true,
      editPermission: 'reviews.manage',
      isDirty: dirty,
      onSave: async () => {
        if (!values.name.trim() || !values.formId || !values.reviewFormId) {
          toast.error('Name, submission form and review form are required.');
          return false;
        }
        const payload: ReviewConfigUpdateInput = {
          name: values.name.trim(),
          formId: values.formId,
          reviewFormId: values.reviewFormId,
          requiredReviewCount: values.requiredReviewCount,
          scoreFieldKey: values.scoreFieldKey,
          windowStart: values.windowStart,
          windowEnd: values.windowEnd,
          reviewStartStatusId: values.reviewStartStatusId,
          revisionsStatusId: values.revisionsStatusId,
          acceptedStatusId: values.acceptedStatusId,
          rejectedStatusId: values.rejectedStatusId,
          isActive: values.isActive,
          roles,
        };
        try {
          await reviewConfigService.update(config.id, payload);
          setDirty(false);
          reload();
          toast.success('Saved.');
          return true;
        } catch (e) {
          toast.error(e instanceof Error ? e.message : 'Could not save.');
          return false;
        }
      },
      onCancel: resetToConfig,
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [config, values, roles, dirty, meta.meta, actorOptions, emsActive, formOptions, submissions]);

  if (loading) {
    return (
      <Container width="fluid">
        <div className="flex items-center justify-center py-24 text-muted-foreground">
          <LoaderCircleIcon className="size-6 animate-spin" />
        </div>
      </Container>
    );
  }

  if (error || !cfgConfig) {
    return (
      <Container width="fluid">
        <div className="py-24 text-center text-sm font-medium">
          {error ?? 'Review process not found.'}
        </div>
      </Container>
    );
  }

  return (
    <Container width="fluid">
      <Form {...form}>
        <ResourceForm config={cfgConfig} />
      </Form>
    </Container>
  );
}
