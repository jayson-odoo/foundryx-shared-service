'use client';

import { useCallback, useEffect, useState } from 'react';
import { toast } from '@/lib/toast';
import {
  getTenantSettings,
  listSettingsAudit,
  updateTenantSettings,
} from '@/services/connector-service';
import type {
  ConnectorSettingsAuditItem,
  ConnectorTenantField,
  ConnectorTenantSettings,
} from '@/types/connector';
import {
  serverFieldErrors,
  TENANT_FIELDS,
  tenantFieldError,
  tenantFormValues,
  toTenantInput,
  type TenantFormValues,
} from './connector-settings-schema';

export interface UseConnectorAccess {
  settings: ConnectorTenantSettings | null;
  audit: ConnectorSettingsAuditItem[];
  isLoading: boolean;
  loadFailed: boolean;
  editing: boolean;
  saving: boolean;
  values: TenantFormValues | null;
  errors: Partial<Record<ConnectorTenantField, string>>;
  reload: () => Promise<void>;
  startEdit: () => void;
  cancel: () => void;
  setValue: (field: ConnectorTenantField, value: string) => void;
  save: () => Promise<void>;
}

/** Access tab: tenant-level connector settings + their change history. */
export function useConnectorAccess(): UseConnectorAccess {
  const [settings, setSettings] = useState<ConnectorTenantSettings | null>(null);
  const [audit, setAudit] = useState<ConnectorSettingsAuditItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [loadFailed, setLoadFailed] = useState(false);
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [values, setValues] = useState<TenantFormValues | null>(null);
  const [errors, setErrors] = useState<Partial<Record<ConnectorTenantField, string>>>({});

  const reload = useCallback(async () => {
    setIsLoading(true);
    try {
      const [s, a] = await Promise.all([getTenantSettings(), listSettingsAudit()]);
      setSettings(s);
      setAudit(a);
      setLoadFailed(false);
    } catch {
      setLoadFailed(true);
      toast.error('Could not load connector settings.');
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  const startEdit = useCallback(() => {
    if (!settings) return;
    setValues(tenantFormValues(settings));
    setErrors({});
    setEditing(true);
  }, [settings]);

  const cancel = useCallback(() => {
    setEditing(false);
    setValues(null);
    setErrors({});
  }, []);

  const setValue = useCallback((field: ConnectorTenantField, value: string) => {
    setValues((v) => (v ? { ...v, [field]: value } : v));
    setErrors((e) => ({ ...e, [field]: undefined }));
  }, []);

  const save = useCallback(async () => {
    if (!values) return;
    const local: Partial<Record<ConnectorTenantField, string>> = {};
    for (const f of TENANT_FIELDS) {
      const err = tenantFieldError(f, values[f]);
      if (err) local[f] = err;
    }
    if (Object.keys(local).length) {
      setErrors(local);
      return;
    }
    setSaving(true);
    try {
      const s = await updateTenantSettings(toTenantInput(values));
      setSettings(s);
      setEditing(false);
      setValues(null);
      toast.success('Settings saved. Changes apply immediately.');
      listSettingsAudit()
        .then(setAudit)
        .catch(() => undefined);
    } catch (e) {
      const fieldErrors = serverFieldErrors(e);
      if (fieldErrors) {
        setErrors(fieldErrors as Partial<Record<ConnectorTenantField, string>>);
        toast.error('Some fields need attention.');
      } else {
        toast.error(e instanceof Error ? e.message : 'Save failed.');
      }
    } finally {
      setSaving(false);
    }
  }, [values]);

  return {
    settings,
    audit,
    isLoading,
    loadFailed,
    editing,
    saving,
    values,
    errors,
    reload,
    startEdit,
    cancel,
    setValue,
    save,
  };
}
