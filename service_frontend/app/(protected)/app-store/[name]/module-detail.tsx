'use client';

/** App Store module detail/form view - read-only facts + the lifecycle actions
 * (install/deactivate/reactivate/update/uninstall) in the form "…" menu, same
 * registry as the list. Own-tenant only. */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useSession } from 'next-auth/react';
import { Info, LoaderCircleIcon } from 'lucide-react';
import { Container } from '@/components/common/container';
import { Label } from '@/components/ui/label';
import { Form } from '@/components/ui/form';
import { useForm } from 'react-hook-form';
import { StatusBadge } from '@/components/platform/status-badge';
import { ResourceForm } from '@/components/platform/resource-form';
import type { ResourceFormConfig } from '@/components/platform/resource-form/types';
import { appStoreService } from '@/services/app-store-service';
import { moduleBadge, type StoreModule } from '@/types/app-store';
import { ModuleCardBody, MODULE_BADGES, buildModuleActions } from '@/components/platform/app-store';

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-1 gap-1.5 md:grid-cols-[200px_1fr] md:items-start md:gap-4">
      <Label className="pt-2 text-sm text-muted-foreground">{label}</Label>
      <div className="max-w-xl">{children}</div>
    </div>
  );
}

export function ModuleDetail({ name }: { name: string }) {
  const { update } = useSession();
  const form = useForm();
  const [module, setModule] = useState<StoreModule | null>(null);
  const [loading, setLoading] = useState(true);
  const [missing, setMissing] = useState(false);

  const load = useCallback(async () => {
    const catalog = await appStoreService.catalog();
    const found = catalog.find((m) => m.name === name) ?? null;
    setModule(found);
    setMissing(!found);
  }, [name]);

  useEffect(() => {
    let active = true;
    load().finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [load]);

  const config = useMemo<ResourceFormConfig<StoreModule> | null>(() => {
    if (!module) return null;
    const installed = module.status !== null;
    return {
      breadcrumb: [{ label: 'App Store', href: '/app-store' }, { label: module.title }],
      backHref: '/app-store',
      backLabel: 'App Store',
      title: module.title,
      subtitle: module.name,
      tabs: [
        {
          id: 'details',
          label: 'Details',
          icon: Info,
          render: () => (
            <div className="flex flex-col gap-6 py-2">
              <div className="max-w-xl rounded-lg border p-5">
                <ModuleCardBody module={module} />
              </div>
              <Row label="Status">
                <StatusBadge status={moduleBadge(module)} registry={MODULE_BADGES} size="sm" />
              </Row>
              <Row label="Version">
                <span className="text-sm">
                  {installed
                    ? `v${module.installedVersion}${module.updateAvailable ? ` → v${module.version} (update available)` : ''}`
                    : `v${module.version}`}
                </span>
              </Row>
              {module.requires && module.requires.length > 0 && (
                <Row label="Requires">
                  <span className="text-sm">{module.requires.map((r) => r.name).join(', ')}</span>
                </Row>
              )}
              {module.optional && module.optional.length > 0 && (
                <Row label="Enhances">
                  <span className="text-sm">{module.optional.map((o) => o.name).join(', ')}</span>
                </Row>
              )}
              {module.provides && module.provides.length > 0 && (
                <Row label="Provides">
                  <span className="text-sm">
                    {module.provides.map((p) => `${p.capability}@${p.version}`).join(', ')}
                  </span>
                </Row>
              )}
              {module.errored && (
                <Row label="Error">
                  <span className="text-destructive text-sm">
                    {module.errorMessage || 'This module failed to load and is unavailable.'}
                  </span>
                </Row>
              )}
            </div>
          ),
        },
      ],
      actions: buildModuleActions(undefined, update),
      actionRows: [module],
      // T5 fix round 2, S2: `StoreModule` has no `.id` - Deactivate's
      // `deferred` park/current/cancel needs an explicit entity id.
      getEntityId: (m) => m.name,
      onReload: () => void load(),
      editable: false,
      isDirty: false,
      onSave: () => true,
      onCancel: () => undefined,
    };
  }, [module, update, load]);

  if (loading) {
    return (
      <Container width="fluid">
        <div className="flex items-center justify-center py-24 text-muted-foreground">
          <LoaderCircleIcon className="size-6 animate-spin" />
        </div>
      </Container>
    );
  }

  if (missing || !config) {
    return (
      <Container width="fluid">
        <div className="py-24 text-center text-sm font-medium">Module not found.</div>
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
