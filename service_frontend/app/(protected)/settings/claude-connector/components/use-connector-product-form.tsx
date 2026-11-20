'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { zodResolver } from '@hookform/resolvers/zod';
import { useForm, type UseFormReturn } from 'react-hook-form';
import { KeyRound, Settings2, SlidersHorizontal, Trash2 } from 'lucide-react';
import { ApiError } from '@/lib/api-client';
import { toast } from '@/lib/toast';
import type { ResourceFormConfig } from '@/components/platform/resource-form';
import type { ResourceAction } from '@/components/platform/resource-list/types';
import {
  createProduct,
  deleteProduct,
  getProductSettings,
  updateProductSettings,
} from '@/services/connector-service';
import type { ConnectorProductSettings, ConnectorProductSettingsInput } from '@/types/connector';
import {
  BLANK_PRODUCT,
  createProductSchema,
  productFormSchema,
  productFormValues,
  serverFieldErrors,
  toProductInput,
  type ProductFormValues,
} from './connector-settings-schema';
import { AdvancedTab, DetailsTab, SecretsTab } from './product-form-fields';

export const CONNECTOR_PATH = '/settings/claude-connector';
export const productPath = (key: string) => `${CONNECTOR_PATH}/products/${encodeURIComponent(key)}`;

export interface UseConnectorProductForm {
  config: ResourceFormConfig<ConnectorProductSettings> | null;
  form: UseFormReturn<ProductFormValues>;
  isLoading: boolean;
  notFound: boolean;
  loadError: boolean;
  retry: () => void;
}

function applyServerErrors(form: UseFormReturn<ProductFormValues>, errors: Record<string, string>) {
  for (const [name, message] of Object.entries(errors)) {
    if (name in BLANK_PRODUCT) form.setError(name as keyof ProductFormValues, { message });
  }
}

/** Create (no key) or view/edit one connector product's settings. */
export function useConnectorProductForm(
  productKey: string | undefined,
  initialEditing: boolean,
): UseConnectorProductForm {
  const router = useRouter();
  const creating = !productKey;
  const [settings, setSettings] = useState<ConnectorProductSettings | null>(null);
  const [isLoading, setIsLoading] = useState(!creating);
  const [notFound, setNotFound] = useState(false);
  const [loadError, setLoadError] = useState(false);
  const [attempt, setAttempt] = useState(0);

  const form = useForm<ProductFormValues>({
    mode: 'onTouched',
    resolver: zodResolver(creating ? createProductSchema : productFormSchema),
    defaultValues: BLANK_PRODUCT,
  });

  useEffect(() => {
    if (creating) return;
    let active = true;
    setIsLoading(true);
    setLoadError(false);
    getProductSettings(productKey)
      .then((s) => {
        if (!active) return;
        setSettings(s);
        form.reset(productFormValues(s));
        setNotFound(false);
      })
      .catch((e) => {
        if (!active) return;
        if (e instanceof ApiError && e.status === 404) setNotFound(true);
        else setLoadError(true);
      })
      .finally(() => active && setIsLoading(false));
    return () => {
      active = false;
    };
  }, [productKey, creating, form, attempt]);

  const onSave = useCallback(async (): Promise<boolean> => {
    if (!(await form.trigger())) return false;
    const input = toProductInput(form.getValues());
    try {
      if (creating) {
        const created = await createProduct(input);
        toast.success('Product saved. Changes apply immediately.');
        router.push(productPath(created.key));
        return true;
      }
      const update: ConnectorProductSettingsInput = { ...input };
      delete (update as Partial<typeof input>).key;
      const updated = await updateProductSettings(productKey, update);
      setSettings(updated);
      form.reset(productFormValues(updated));
      toast.success('Settings saved. Changes apply immediately.');
      return true;
    } catch (e) {
      const errors = serverFieldErrors(e);
      if (errors) {
        applyServerErrors(form, errors);
        const secrets = 'ssToProductSecret' in errors || 'productToSsSecret' in errors;
        toast.error(secrets ? 'Check the Secrets tab.' : 'Some fields need attention.');
      } else {
        toast.error(e instanceof Error ? e.message : 'Save failed.');
      }
      return false;
    }
  }, [creating, form, productKey, router]);

  const actions = useMemo<ResourceAction<ConnectorProductSettings>[]>(
    () => [
      {
        id: 'delete-product',
        label: 'Delete saved settings',
        icon: Trash2,
        tone: 'destructive',
        surfaces: { form: true },
        permission: 'connector.settings',
        isVisible: (rows) => rows.length === 1 && rows[0].stored,
        confirm: {
          title: (rows) => `Delete the saved settings for ${rows[0]?.key}?`,
          description:
            'Saved values and secrets are removed. Values from the server environment, if any, take over.',
          confirmLabel: 'Delete',
          input: { expected: (rows) => rows[0]?.key ?? '' },
        },
        run: async (rows, runtime) => {
          const key = rows[0]?.key;
          if (!key) return;
          try {
            await deleteProduct(key, key);
            toast.success('Saved settings deleted.');
            router.push(runtime.backHref ?? CONNECTOR_PATH);
          } catch (e) {
            toast.error(e instanceof Error ? e.message : 'Delete failed.');
          }
        },
      },
    ],
    [router],
  );

  const config = useMemo<ResourceFormConfig<ConnectorProductSettings> | null>(() => {
    if (isLoading || notFound || loadError) return null;
    const title = creating ? 'New product' : (settings?.fields.displayName.value ?? productKey ?? '');
    return {
      breadcrumb: [
        { label: 'Home', href: '/' },
        { label: 'Settings' },
        { label: 'Claude connector', href: CONNECTOR_PATH },
        { label: title },
      ],
      backHref: CONNECTOR_PATH,
      backLabel: 'Back to Claude connector',
      title,
      entityNoun: 'product',
      subtitle: creating ? undefined : productKey,
      tabs: [
        {
          id: 'details',
          label: 'Details',
          icon: Settings2,
          render: ({ editing }) => (
            <DetailsTab form={form} editing={editing} creating={creating} settings={settings} />
          ),
        },
        {
          id: 'secrets',
          label: 'Secrets',
          icon: KeyRound,
          render: ({ editing }) => (
            <SecretsTab form={form} editing={editing} creating={creating} settings={settings} />
          ),
        },
        {
          id: 'advanced',
          label: 'Advanced',
          icon: SlidersHorizontal,
          render: ({ editing }) => (
            <AdvancedTab form={form} editing={editing} creating={creating} settings={settings} />
          ),
        },
      ],
      actions,
      actionRows: settings ? [settings] : [],
      getEntityId: (row) => row.key,
      editable: !creating,
      editPermission: 'connector.settings',
      initialEditing: creating ? true : initialEditing,
      isDirty: form.formState.isDirty,
      onSave,
      onCancel: () => {
        if (creating) {
          router.push(CONNECTOR_PATH);
          return;
        }
        if (settings) form.reset(productFormValues(settings));
      },
    };
  }, [isLoading, notFound, loadError, creating, settings, productKey, form, actions, initialEditing, onSave, router]);

  return { config, form, isLoading, notFound, loadError, retry: () => setAttempt((n) => n + 1) };
}
