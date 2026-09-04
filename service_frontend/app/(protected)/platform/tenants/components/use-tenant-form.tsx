'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { zodResolver } from '@hookform/resolvers/zod';
import { Blocks, Building2, Palette } from 'lucide-react';
import { useForm, type UseFormReturn } from 'react-hook-form';
import { toast } from 'sonner';
import type { TenantDetail, TenantListItem } from '@/types/tenant-admin';
import { tenantAdminService } from '@/services/tenant-admin-service';
import type { ResourceFormConfig } from '@/components/platform/resource-form';
import type { ListQuery } from '@/types/resource';
import { tenantFormHref, tenantFormPath, tenantsListPath } from './paths';
import { BrandingTab, DetailsTab, ModulesTab } from './tenant-form-fields';
import {
  tenantProvisionSchema,
  tenantUpdateSchema,
  type TenantFormValues,
} from './tenant-schema';
import { useTenantActions } from './use-tenant-actions';

function toFormValues(tenant: TenantDetail | null): TenantFormValues {
  return {
    name: tenant?.name ?? '',
    slug: tenant?.slug ?? '',
    contactName: tenant?.contactName ?? '',
    contactEmail: tenant?.contactEmail ?? '',
    customDomain: tenant?.customDomain ?? '',
    notes: tenant?.notes ?? '',
    adminName: '',
    adminEmail: '',
    adminPassword: '',
  };
}

const orNull = (v: string): string | null => (v.trim() ? v.trim() : null);

export interface UseTenantFormResult {
  config: ResourceFormConfig<TenantListItem> | null;
  form: UseFormReturn<TenantFormValues>;
  isLoading: boolean;
  notFound: boolean;
}

/** Loads the record, wires RHF (provision vs update schema), assembles the form config. */
export function useTenantForm(
  tenantId: string | undefined,
  initialEditing: boolean,
): UseTenantFormResult {
  const router = useRouter();
  const actions = useTenantActions();
  const creating = !tenantId;

  const [tenant, setTenant] = useState<TenantDetail | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);

  const form = useForm<TenantFormValues>({
    resolver: zodResolver(
      creating ? tenantProvisionSchema : tenantUpdateSchema,
    ),
    defaultValues: toFormValues(null),
  });

  // Load the record (or start blank for create).
  useEffect(() => {
    let active = true;
    if (creating) {
      setTenant(null);
      form.reset(toFormValues(null));
      setIsLoading(false);
      return;
    }
    setIsLoading(true);
    tenantAdminService
      .get(tenantId)
      .then((t) => {
        if (!active) return;
        setTenant(t);
        form.reset(toFormValues(t));
        setNotFound(false);
      })
      .catch(() => active && setNotFound(true))
      .finally(() => active && setIsLoading(false));
    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tenantId, creating]);

  // Stable across renders (fix round 2, AC-DLA-30/31 D7) - see use-user-form.tsx.
  const fetchRecordAt = useCallback(
    (query: ListQuery, index: number) =>
      tenantAdminService.getAt(query, index).then((r) => ({
        recordId: r.tenant?.id ?? null,
        total: r.total,
      })),
    [],
  );
  const buildRecordHref = useCallback(
    (recordId: string, ctx: string, index: number) => tenantFormHref(recordId, { ctx, index }),
    [],
  );

  const config = useMemo<ResourceFormConfig<TenantListItem> | null>(() => {
    if (isLoading || notFound) return null;

    const onSave = async (): Promise<boolean> => {
      let ok = false;
      await form.handleSubmit(async (values) => {
        try {
          if (creating) {
            const created = await tenantAdminService.provision({
              name: values.name,
              slug: values.slug,
              contactName: orNull(values.contactName),
              contactEmail: orNull(values.contactEmail),
              notes: orNull(values.notes),
              adminName: values.adminName,
              adminEmail: values.adminEmail,
              adminPassword: values.adminPassword,
            });
            toast.success('Tenant provisioned.');
            router.push(tenantFormPath(created.id));
          } else {
            const updated = await tenantAdminService.update(tenantId, {
              name: values.name,
              contactName: orNull(values.contactName),
              contactEmail: orNull(values.contactEmail),
              customDomain: orNull(values.customDomain),
              notes: orNull(values.notes),
            });
            setTenant(updated);
            form.reset(toFormValues(updated));
            toast.success('Tenant updated.');
          }
          ok = true;
        } catch (e) {
          // Server-side slug guard (taken/reserved) surfaces here.
          toast.error(e instanceof Error ? e.message : 'Something went wrong.');
        }
      })();
      return ok;
    };

    const onCancel = () => {
      if (creating) router.push(tenantsListPath);
      else form.reset(toFormValues(tenant));
    };

    const tabs = [
      {
        id: 'details',
        label: 'Details',
        icon: Building2,
        render: ({ editing }: { editing: boolean }) => (
          <DetailsTab
            form={form}
            editing={editing}
            tenant={tenant}
            creating={creating}
          />
        ),
      },
      {
        id: 'modules',
        label: 'Modules',
        icon: Blocks,
        render: () => <ModulesTab tenant={tenant} />,
      },
      {
        id: 'branding',
        label: 'Branding',
        icon: Palette,
        render: () => <BrandingTab tenant={tenant} />,
      },
    ];

    return {
      breadcrumb: [
        { label: 'Home', href: '/' },
        { label: 'Platform', href: tenantsListPath },
        { label: 'Tenants', href: tenantsListPath },
        { label: creating ? 'New tenant' : (tenant?.name ?? 'Tenant') },
      ],
      backHref: tenantsListPath,
      backLabel: 'Back to tenants',
      title: creating ? 'New tenant' : (tenant?.name ?? 'Tenant'),
      subtitle: creating
        ? 'Provision a tenant with its first admin user'
        : (tenant?.slug ?? undefined),
      tabs,
      initialTabId: 'details',
      actions,
      actionRows: tenant ? [tenant] : [],
      editable: !creating,
      editPermission: 'tenants.update',
      initialEditing: creating ? true : initialEditing,
      isDirty: form.formState.isDirty,
      onSave,
      onCancel,
      recordNav: creating
        ? undefined
        : { fetchAt: fetchRecordAt, buildHref: buildRecordHref },
    };
  }, [
    isLoading,
    notFound,
    creating,
    tenant,
    actions,
    form,
    initialEditing,
    tenantId,
    router,
    fetchRecordAt,
    buildRecordHref,
  ]);

  return { config, form, isLoading, notFound };
}
