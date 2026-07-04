'use client';

/** Profile detail/form view — read + Edit-toggle fields, with the tier-1 status
 * shown and changed straight from the form "…" (the graph's available next
 * states). Mirrors the list-view status change. */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useForm } from 'react-hook-form';
import { ArrowRight, IdCard, Info, LoaderCircleIcon, Send } from 'lucide-react';
import { toast } from 'sonner';
import { Container } from '@/components/common/container';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Form } from '@/components/ui/form';
import { ResourceForm } from '@/components/platform/resource-form';
import type { ResourceFormConfig } from '@/components/platform/resource-form/types';
import type { ResourceAction } from '@/components/platform/resource-list';
import { useStatusGraph } from '@/hooks/use-status-engine';
import { useTerminology } from '@/hooks/use-terminology';
import { emsService } from '@/services/ems-service';
import { personaService } from '@/services/persona-service';
import type { Profile } from '@/types/ems';
import { ProfilePersonasTab } from './profile-personas-tab';

const PROFILE_ENTITY = 'profile';

interface DetailValues {
  fullName: string;
  phone: string;
  country: string;
  organization: string;
  title: string;
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-1 gap-1.5 md:grid-cols-[200px_1fr] md:items-start md:gap-4">
      <Label className="pt-2 text-sm text-muted-foreground">{label}</Label>
      <div className="max-w-xl">{children}</div>
    </div>
  );
}

export function ProfileDetail({ profileId }: { profileId: string }) {
  const { labelPlural } = useTerminology();
  const engine = useStatusGraph(PROFILE_ENTITY);
  const form = useForm<DetailValues>({
    defaultValues: { fullName: '', phone: '', country: '', organization: '', title: '' },
  });

  const [record, setRecord] = useState<Profile | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    return emsService.getProfile(profileId).then((p) => {
      setRecord(p);
      form.reset({
        fullName: p.fullName ?? '',
        phone: p.phone ?? '',
        country: p.country ?? '',
        organization: p.organization ?? '',
        title: p.title ?? '',
      });
    });
  }, [profileId, form]);

  useEffect(() => {
    let active = true;
    load().finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [load]);

  const values = form.watch();
  const statusLabel = useMemo(() => {
    const s = engine.graph?.statuses.find((x) => x.id === record?.statusId);
    return s?.label ?? '';
  }, [engine.graph, record?.statusId]);

  const config = useMemo<ResourceFormConfig<Profile> | null>(() => {
    if (!record) return null;

    // Form "…" actions: one per available next status (off the graph).
    const moves = record.statusId
      ? (engine.graph?.transitions ?? []).filter((t) => t.fromStatusId === record.statusId)
      : [];
    const statusName = (id: string) =>
      engine.graph?.statuses.find((s) => s.id === id)?.label ?? id;
    const actions: ResourceAction<Profile>[] = moves.map((t) => ({
      id: `move-${t.toStatusId}`,
      label: `${statusName(t.toStatusId)}`,
      icon: ArrowRight,
      surfaces: { row: false, form: true, bulk: false },
      permission: 'profiles.manage',
      run: async (_rows, runtime) => {
        try {
          await emsService.transitionProfile(record.id, t.toStatusId);
          runtime.reload();
        } catch (e) {
          toast.error(e instanceof Error ? e.message : 'Could not change the status.');
        }
      },
    }));

    // Staff "Send portal invite" (AC-06-15c) — gated personas.manage. Disabled
    // (not hidden) when the profile has no email, so the reason is self-evident.
    actions.push({
      id: 'send-portal-invite',
      label: 'Send portal invite',
      icon: Send,
      surfaces: { row: false, form: true, bulk: false },
      permission: 'personas.manage',
      isDisabled: (rows) => !(rows[0]?.email ?? '').trim(),
      run: async ([row]) => {
        try {
          const res = await personaService.sendPortalInvite(row.id);
          toast.success(`Portal invite sent to ${res.email}.`);
        } catch (e) {
          toast.error(e instanceof Error ? e.message : 'Could not send the invite.');
        }
      },
    });

    return {
      breadcrumb: [{ label: labelPlural('profile'), href: '/ems/profiles' }, { label: record.fullName || record.email }],
      backHref: '/ems/profiles',
      backLabel: labelPlural('profile'),
      title: record.fullName || record.email,
      subtitle: record.email,
      tabs: [
        {
          id: 'details',
          label: 'Details',
          icon: Info,
          render: ({ editing }) => (
            <div className="flex flex-col gap-5 py-2">
              <Row label="Status">
                {statusLabel ? (
                  <Badge variant="primary" appearance="light" size="sm">{statusLabel}</Badge>
                ) : (
                  <span className="text-sm text-muted-foreground">—</span>
                )}
              </Row>
              <Row label="Email">
                <span className="text-sm">{record.email}</span>
              </Row>
              {(
                [
                  ['fullName', 'Full name'],
                  ['phone', 'Phone'],
                  ['organization', 'Organization'],
                  ['title', 'Title'],
                  ['country', 'Country'],
                ] as [keyof DetailValues, string][]
              ).map(([key, lbl]) => (
                <Row key={key} label={lbl}>
                  {editing ? (
                    <Input
                      aria-label={lbl}
                      value={values[key]}
                      onChange={(e) => form.setValue(key, e.target.value, { shouldDirty: true })}
                    />
                  ) : (
                    <span className="text-sm">{values[key] || '—'}</span>
                  )}
                </Row>
              ))}
            </div>
          ),
        },
        {
          id: 'personas',
          label: 'Personas',
          icon: IdCard,
          render: () => (
            <ProfilePersonasTab profileId={record.id} profileEmail={record.email} />
          ),
        },
      ],
      actions,
      actionRows: [record],
      onReload: () => load(),
      editable: true,
      editPermission: 'profiles.manage',
      isDirty: form.formState.isDirty,
      onSave: async () => {
        const updated = await emsService.updateProfile(record.id, {
          fullName: values.fullName,
          phone: values.phone,
          country: values.country,
          organization: values.organization,
          title: values.title,
        });
        setRecord(updated);
        form.reset({
          fullName: updated.fullName ?? '',
          phone: updated.phone ?? '',
          country: updated.country ?? '',
          organization: updated.organization ?? '',
          title: updated.title ?? '',
        });
        return true;
      },
      onCancel: () =>
        form.reset({
          fullName: record.fullName ?? '',
          phone: record.phone ?? '',
          country: record.country ?? '',
          organization: record.organization ?? '',
          title: record.title ?? '',
        }),
    };
  }, [record, engine.graph, values, form, statusLabel, labelPlural, load]);

  if (loading || engine.loading) {
    return (
      <Container width="fluid">
        <div className="flex items-center justify-center py-24 text-muted-foreground">
          <LoaderCircleIcon className="size-6 animate-spin" />
        </div>
      </Container>
    );
  }

  if (!config) {
    return (
      <Container width="fluid">
        <div className="py-24 text-center text-sm font-medium">Profile not found.</div>
      </Container>
    );
  }

  return (
    <Container width="fluid">
      <Form {...form}>
        <ResourceForm config={config} />
      </Form>
    </Container>
  );
}
