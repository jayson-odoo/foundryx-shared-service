'use client';

import { useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { zodResolver } from '@hookform/resolvers/zod';
import { useForm, type UseFormReturn } from 'react-hook-form';
import { Plug } from 'lucide-react';
import { toast } from 'sonner';
import type { ResourceFormConfig } from '@/components/platform/resource-form';
import { integrationService } from '@/services/integration-service';
import type { Connection, IntegrationProvider } from '@/types/integration';
import { ConfigurationTab, HealthCard } from './connection-form-fields';
import { useConnectionActions } from './use-connection-actions';
import { connectionFormHref, connectionFormPath, integrationsListPath } from './paths';
import {
  connectionFormSchema,
  defaultsForProvider,
  requiredFieldErrors,
  toConnectionInput,
  valuesForConnection,
  type ConnectionFormValues,
} from './connection-schema';

const BLANK: ConnectionFormValues = { provider: '', name: '', config: {}, credentials: {} };

export interface UseConnectionFormResult {
  config: ResourceFormConfig<Connection> | null;
  form: UseFormReturn<ConnectionFormValues>;
  isLoading: boolean;
  notFound: boolean;
}

/** Loads the record + catalog, wires RHF, and assembles the form config. */
export function useConnectionForm(
  connectionId: string | undefined,
  initialEditing: boolean,
): UseConnectionFormResult {
  const router = useRouter();
  const actions = useConnectionActions();
  const creating = !connectionId;

  const [connection, setConnection] = useState<Connection | null>(null);
  const [providers, setProviders] = useState<IntegrationProvider[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);

  const form = useForm<ConnectionFormValues>({
    resolver: zodResolver(connectionFormSchema),
    defaultValues: BLANK,
  });

  // The picked provider drives the dynamic field schema.
  const providerKey = form.watch('provider');
  const provider = useMemo(
    () => providers.find((p) => p.provider === providerKey) ?? null,
    [providers, providerKey],
  );

  // Load the catalog once.
  useEffect(() => {
    integrationService.providers().then(setProviders).catch(() => setProviders([]));
  }, []);

  // Load the record (or start blank for create).
  useEffect(() => {
    let active = true;
    if (creating) {
      setConnection(null);
      form.reset(BLANK);
      setIsLoading(false);
      return;
    }
    setIsLoading(true);
    integrationService
      .get(connectionId)
      .then((c) => {
        if (!active) return;
        setConnection(c);
        setNotFound(false);
      })
      .catch(() => active && setNotFound(true))
      .finally(() => active && setIsLoading(false));
    return () => {
      active = false;
    };
  }, [connectionId, creating, form]);

  // Prefill once BOTH the record and its provider schema are known.
  useEffect(() => {
    if (!connection) return;
    const p = providers.find((x) => x.provider === connection.provider);
    if (!p) return;
    form.reset(valuesForConnection(p, connection));
  }, [connection, providers, form]);

  const onProviderChange = (key: string) => {
    const p = providers.find((x) => x.provider === key);
    if (!p) return;
    // Re-seed the whole form — field sets differ per provider.
    form.reset(defaultsForProvider(p));
  };

  const onSave = async (): Promise<boolean> => {
    const valid = await form.trigger();
    if (!valid) return false;
    const values = form.getValues();
    if (!provider) {
      form.setError('provider', { message: 'Pick a provider.' });
      return false;
    }
    // Per-provider required checks (dynamic fields sit outside the zod base).
    const errors = requiredFieldErrors(provider, values, creating);
    if (errors.length) {
      for (const e of errors) form.setError(e.path, { message: e.message });
      return false;
    }
    try {
      const input = toConnectionInput(values);
      if (creating) {
        const created = await integrationService.create(input);
        toast.success(`${created.name} connected — run a test to verify it.`);
        router.push(connectionFormPath(created.id));
        return true;
      }
      const updated = await integrationService.update(connection!.id, input);
      setConnection(updated);
      form.reset(valuesForConnection(provider, updated));
      toast.success('Connection saved.');
      return true;
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Save failed.');
      return false;
    }
  };

  const config = useMemo<ResourceFormConfig<Connection> | null>(() => {
    if (isLoading || notFound) return null;

    return {
      breadcrumb: [
        { label: 'Home', href: '/' },
        { label: 'Settings' },
        { label: 'Integrations', href: integrationsListPath },
        { label: creating ? 'New integration' : (connection?.name ?? 'Connection') },
      ],
      backHref: integrationsListPath,
      backLabel: 'Back to integrations',
      title: creating ? 'Connect integration' : (connection?.name ?? 'Connection'),
      subtitle: creating
        ? 'Connect an external service to this workspace'
        : (provider?.title ?? connection?.provider),
      tabs: [
        {
          id: 'configuration',
          label: 'Configuration',
          icon: Plug,
          render: ({ editing }) => (
            <>
              <ConfigurationTab
                form={form}
                editing={editing}
                creating={creating}
                providers={providers}
                provider={provider}
                onProviderChange={onProviderChange}
                connection={connection}
              />
              {!creating && connection && (
                <HealthCard
                  connection={connection}
                  provider={provider}
                  canManage
                  onChanged={(c) => c && setConnection(c)}
                />
              )}
            </>
          ),
        },
      ],
      actions,
      actionRows: connection ? [connection] : [],
      // Form-surface Test flips status/lastTestedAt — re-pull the record so
      // the Health card reflects it without a page refresh.
      onReload: () => {
        if (!connection) return;
        integrationService
          .get(connection.id)
          .then(setConnection)
          .catch(() => {});
      },
      editable: !creating,
      editPermission: 'integrations.manage',
      initialEditing: creating ? true : initialEditing,
      isDirty: form.formState.isDirty,
      onSave,
      onCancel: () => {
        if (creating) {
          router.push(integrationsListPath);
          return;
        }
        if (connection && provider) form.reset(valuesForConnection(provider, connection));
      },
      recordNav: creating
        ? undefined
        : {
            fetchAt: (query, index) =>
              integrationService.getAt(query, index).then((r) => ({
                recordId: r.connection?.id ?? null,
                total: r.total,
              })),
            buildHref: (recordId, ctx, index) =>
              connectionFormHref(recordId, { ctx, index }),
          },
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isLoading, notFound, creating, connection, providers, provider, actions, form, initialEditing, router]);

  return { config, form, isLoading, notFound };
}
