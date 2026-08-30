'use client';

import { useEffect, useState } from 'react';
import type { UseFormReturn } from 'react-hook-form';
import { ChevronDown, LoaderCircleIcon, Send } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import {
  FormControl,
  FormField,
  FormItem,
  FormMessage,
} from '@/components/ui/form';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { FormRow } from '@/components/platform/resource-form';
import { ClampedText } from '@/components/platform/clamped-text';
import { SearchSelect, type SearchSelectGroup } from '@/components/platform/search-select';
import { SecretInput } from '@/components/platform/secret-input';
import { StatusBadge } from '@/components/platform/status-badge';
import { integrationService } from '@/services/integration-service';
import { useDatetime } from '@/hooks/use-datetime';
import type { Connection, IntegrationProvider, ProviderField } from '@/types/integration';
import { CONNECTION_STATUS_REGISTRY } from './connection-status';
import { dependentDefault, type ConnectionFormValues } from './connection-schema';

const TYPE_LABELS: Record<string, string> = {
  email: 'Email',
  storage: 'Storage',
  llm: 'LLM',
  erp: 'ERP',
};

export interface ConfigurationTabProps {
  form: UseFormReturn<ConnectionFormValues>;
  editing: boolean;
  creating: boolean;
  /** Full catalog (create: drives the provider picker). */
  providers: IntegrationProvider[];
  /** The selected/locked provider (null until picked on create). */
  provider: IntegrationProvider | null;
  onProviderChange: (provider: string) => void;
  connection: Connection | null;
}

/** Provider picker groups, sectioned by integration type. */
function providerGroups(providers: IntegrationProvider[]): SearchSelectGroup[] {
  const byType = new Map<string, IntegrationProvider[]>();
  for (const p of providers) {
    byType.set(p.type, [...(byType.get(p.type) ?? []), p]);
  }
  return Array.from(byType.entries()).map(([type, list]) => ({
    label: TYPE_LABELS[type] ?? type,
    options: list.map((p: IntegrationProvider) => ({ label: p.title, value: p.provider })),
  }));
}

function fieldName(f: ProviderField): `config.${string}` | `credentials.${string}` {
  return f.secret ? `credentials.${f.key}` : `config.${f.key}`;
}

/** One provider-declared field - control by type, read mode shows the value. */
function ProviderFieldRow({
  f,
  form,
  editing,
  creating,
  connection,
}: {
  f: ProviderField;
  form: UseFormReturn<ConnectionFormValues>;
  editing: boolean;
  creating: boolean;
  connection: Connection | null;
}) {
  if (!editing) {
    const value = f.secret ? undefined : (connection?.config[f.key] ?? '');
    return (
      <FormRow label={f.label}>
        {f.secret ? (
          <span className="text-muted-foreground">••••••••</span>
        ) : f.type === 'select' ? (
          (f.options?.find((o) => o.value === value)?.label ?? (value || '-'))
        ) : (
          value || '-'
        )}
      </FormRow>
    );
  }

  return (
    <FormRow label={f.label} required={f.required && (creating || !f.secret)}>
      <FormField
        control={form.control}
        name={fieldName(f)}
        render={({ field }) => (
          <FormItem className="max-w-sm">
            <FormControl>
              {f.secret ? (
                <SecretInput
                  placeholder={creating ? f.placeholder : '•••••••• (leave blank to keep)'}
                  {...field}
                  value={field.value ?? ''}
                />
              ) : f.type === 'select' ? (
                <Select value={field.value ?? ''} onValueChange={field.onChange}>
                  <SelectTrigger>
                    <SelectValue placeholder={f.placeholder} />
                  </SelectTrigger>
                  <SelectContent>
                    {(f.options ?? []).map((o) => (
                      <SelectItem key={o.value} value={o.value}>
                        {o.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              ) : (
                <Input
                  type={f.type === 'number' ? 'number' : 'text'}
                  placeholder={f.placeholder}
                  {...field}
                  value={field.value ?? ''}
                />
              )}
            </FormControl>
            <FormMessage />
          </FormItem>
        )}
      />
    </FormRow>
  );
}

export function ConfigurationTab({
  form,
  editing,
  creating,
  providers,
  provider,
  onProviderChange,
  connection,
}: ConfigurationTabProps) {
  const [showAdvanced, setShowAdvanced] = useState(false);

  // Registry-driven dependent defaults (`ProviderField.defaultsFrom`): when a
  // driver select changes, reset its dependants that still hold a stock
  // default (the SQL provider's port follows its dialect, AC-22-04). Generic -
  // no provider-specific branch here.
  useEffect(() => {
    const dependants = (provider?.fields ?? []).filter((f) => f.defaultsFrom && !f.secret);
    if (dependants.length === 0) return;
    const subscription = form.watch((values, { name }) => {
      if (!name?.startsWith('config.')) return;
      const driverKey = name.slice('config.'.length);
      for (const f of dependants) {
        if (f.defaultsFrom?.field !== driverKey) continue;
        const next = dependentDefault(
          f,
          values.config?.[driverKey] ?? '',
          values.config?.[f.key] ?? '',
        );
        if (next !== null) form.setValue(`config.${f.key}`, next, { shouldDirty: true });
      }
    });
    return () => subscription.unsubscribe();
  }, [form, provider]);

  const basic = provider?.fields.filter((f) => !f.advanced) ?? [];
  const advanced = provider?.fields.filter((f) => f.advanced) ?? [];
  // Read mode: surface advanced fields that actually hold a value.
  const advancedVisible = editing
    ? showAdvanced
    : advanced.some((f) => !f.secret && (connection?.config[f.key] ?? '') !== '');

  return (
    <Card>
      <CardContent className="py-1">
        <FormRow label="Provider" required={creating}>
          {creating ? (
            <FormField
              control={form.control}
              name="provider"
              render={({ field }) => (
                <FormItem className="max-w-sm">
                  <FormControl>
                    <SearchSelect
                      groups={providerGroups(providers)}
                      value={field.value || null}
                      onChange={onProviderChange}
                      placeholder="Pick a provider…"
                      ariaLabel="Provider"
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
          ) : (
            <div className="flex flex-col">
              <span>{provider?.title ?? connection?.provider}</span>
              <span className="text-xs text-muted-foreground">
                {TYPE_LABELS[connection?.type ?? ''] ?? connection?.type}
              </span>
            </div>
          )}
        </FormRow>

        {provider && (
          <FormRow label="Name" required={editing}>
            {editing ? (
              <FormField
                control={form.control}
                name="name"
                render={({ field }) => (
                  <FormItem className="max-w-sm">
                    <FormControl>
                      <Input placeholder="e.g. Company mail server" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            ) : (
              (connection?.name ?? '-')
            )}
          </FormRow>
        )}

        {provider && (
          <>
            {basic.map((f) => (
              <ProviderFieldRow
                key={f.key}
                f={f}
                form={form}
                editing={editing}
                creating={creating}
                connection={connection}
              />
            ))}

            {advanced.length > 0 && editing && (
              <div className="py-2.5">
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => setShowAdvanced((s) => !s)}
                >
                  <ChevronDown
                    className={showAdvanced ? 'rotate-180 transition-transform' : 'transition-transform'}
                  />
                  Advanced
                </Button>
              </div>
            )}
            {advancedVisible &&
              advanced.map((f) => (
                <ProviderFieldRow
                  key={f.key}
                  f={f}
                  form={form}
                  editing={editing}
                  creating={creating}
                  connection={connection}
                />
              ))}
          </>
        )}
      </CardContent>
    </Card>
  );
}

export interface HealthCardProps {
  connection: Connection;
  provider: IntegrationProvider | null;
  canManage: boolean;
  /** Refresh the record after a test settles status/lastTestedAt. */
  onChanged: (c: Connection | null) => void;
}

/**
 * Connection health + the provider's OPTIONAL targeted test (SMTP: send a
 * real email - needs an input, so it lives here rather than in the action
 * registry). The plain connection check is the registry's Test action.
 */
export function HealthCard({ connection, provider, canManage, onChanged }: HealthCardProps) {
  const [target, setTarget] = useState('');
  const [busy, setBusy] = useState(false);
  // Session-tz formatter (plan sprint-2/05) - never the tz-blind lib/format.
  const { formatDateTime } = useDatetime();

  const runTargeted = async () => {
    if (!target.trim()) return;
    setBusy(true);
    try {
      const result = await integrationService.test(connection.id, target.trim());
      if (result.ok) toast.success(result.message);
      else toast.error(result.message);
      onChanged(await integrationService.get(connection.id));
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Test failed.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card className="mt-5">
      <CardContent className="py-1">
        <FormRow label="Status">
          <StatusBadge status={connection.status} registry={CONNECTION_STATUS_REGISTRY} />
        </FormRow>
        <FormRow label="Last tested">
          {connection.lastTestedAt ? formatDateTime(connection.lastTestedAt) : 'Never'}
        </FormRow>
        {connection.lastError && (
          <FormRow label="Last error">
            <ClampedText text={connection.lastError} lines={2} className="text-destructive" />
          </FormRow>
        )}
        {canManage && provider?.testTarget && (
          <FormRow label={provider.testTarget.label}>
            <div className="flex max-w-sm items-center gap-2">
              <Input
                value={target}
                placeholder={provider.testTarget.placeholder}
                onChange={(e) => setTarget(e.target.value)}
                disabled={busy}
              />
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => void runTargeted()}
                disabled={busy || !target.trim()}
              >
                {busy ? <LoaderCircleIcon className="size-3.5 animate-spin" /> : <Send className="size-3.5" />}
                {provider.testLabel}
              </Button>
            </div>
          </FormRow>
        )}
      </CardContent>
    </Card>
  );
}
