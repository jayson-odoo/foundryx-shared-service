'use client';

import type { UseFormReturn } from 'react-hook-form';
import { FormControl, FormField, FormItem, FormMessage } from '@/components/ui/form';
import { Input } from '@/components/ui/input';
import { Checkbox } from '@/components/ui/checkbox';
import { Badge } from '@/components/ui/badge';
import { FormRow } from '@/components/platform/resource-form';
import { SecretInput } from '@/components/platform/secret-input';
import type {
  ConnectorProductField,
  ConnectorProductSettings,
  ConnectorSecretSlot,
} from '@/types/connector';
import { fallbackHint, type ProductFormValues } from './connector-settings-schema';
import { SourceBadge } from './source-badge';

export const FIELD_LABELS: Record<ConnectorProductField, string> = {
  displayName: 'Display name',
  connectionId: 'Connection ID',
  consentUrl: 'Consent URL',
  apiBaseUrl: 'API base URL',
  issuer: 'Issuer',
  consentAudience: 'Consent audience',
  callAudience: 'Call audience',
};

const REQUIRED: ConnectorProductField[] = ['connectionId', 'consentUrl', 'apiBaseUrl'];

export interface ProductFieldsProps {
  form: UseFormReturn<ProductFormValues>;
  editing: boolean;
  creating: boolean;
  settings: ConnectorProductSettings | null;
}

function ReadValue({ settings, field }: { settings: ConnectorProductSettings | null; field: ConnectorProductField }) {
  const v = settings?.fields[field];
  return (
    <div className="flex min-w-0 flex-wrap items-center gap-2">
      <span className="min-w-0 break-all font-mono text-xs">{v?.value || '-'}</span>
      {v && <SourceBadge source={v.source} />}
    </div>
  );
}

function FieldRows({ form, editing, creating, settings, fields }: ProductFieldsProps & { fields: ConnectorProductField[] }) {
  return (
    <>
      {fields.map((f) =>
        editing ? (
          <FormRow key={f} label={FIELD_LABELS[f]} required={REQUIRED.includes(f)}>
            <FormField
              control={form.control}
              name={f}
              render={({ field }) => (
                <FormItem className="max-w-xl">
                  <FormControl>
                    <Input
                      {...field}
                      aria-label={FIELD_LABELS[f]}
                      placeholder={creating ? undefined : fallbackHint(settings, f)}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
          </FormRow>
        ) : (
          <FormRow key={f} label={FIELD_LABELS[f]}>
            <ReadValue settings={settings} field={f} />
          </FormRow>
        ),
      )}
    </>
  );
}

export function DetailsTab(props: ProductFieldsProps) {
  const { form, editing, creating, settings } = props;
  return (
    <div className="flex flex-col">
      <FormRow label="Key" required={creating}>
        {creating ? (
          <FormField
            control={form.control}
            name="key"
            render={({ field }) => (
              <FormItem className="max-w-xs">
                <FormControl>
                  <Input {...field} aria-label="Key" autoComplete="off" />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
        ) : (
          <span className="font-mono text-xs">{settings?.key}</span>
        )}
      </FormRow>
      {!creating && settings && (
        <FormRow label="Status">
          <Badge
            variant={settings.status === 'ok' ? 'success' : 'destructive'}
            appearance="light"
            size="sm"
          >
            {settings.status === 'ok' ? 'Ready' : 'Misconfigured'}
          </Badge>
        </FormRow>
      )}
      <FieldRows {...props} editing={editing} fields={['displayName', 'connectionId', 'consentUrl', 'apiBaseUrl']} />
    </div>
  );
}

export function AdvancedTab(props: ProductFieldsProps) {
  return (
    <div className="flex flex-col">
      <FieldRows {...props} fields={['issuer', 'consentAudience', 'callAudience']} />
    </div>
  );
}

const SECRET_ROWS: { slot: ConnectorSecretSlot; name: 'ssToProductSecret' | 'productToSsSecret'; label: string }[] = [
  { slot: 'ssToProduct', name: 'ssToProductSecret', label: 'Secret to product' },
  { slot: 'productToSs', name: 'productToSsSecret', label: 'Secret from product' },
];

const STATE_LABEL = { set: 'Set', missing: 'Missing', unreadable: 'Unreadable - re-enter' } as const;

export function SecretsTab({ form, editing, creating, settings }: ProductFieldsProps) {
  const clear = form.watch('clearSecrets');
  return (
    <div className="flex flex-col">
      {SECRET_ROWS.map(({ slot, name, label }) => {
        const s = settings?.secrets[slot];
        const status = s && (
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant={s.state === 'set' ? 'success' : 'destructive'} appearance="light" size="sm">
              {STATE_LABEL[s.state]}
            </Badge>
            {s.state !== 'missing' && <SourceBadge source={s.source} />}
          </div>
        );
        if (!editing) {
          return (
            <FormRow key={slot} label={label}>
              {status ?? '-'}
            </FormRow>
          );
        }
        const canClear = !creating && s?.source === 'database';
        return (
          <FormRow key={slot} label={label} required={creating}>
            <div className="flex max-w-xl flex-col gap-2">
              {status}
              <FormField
                control={form.control}
                name={name}
                render={({ field }) => (
                  <FormItem>
                    <FormControl>
                      <SecretInput
                        {...field}
                        aria-label={label}
                        autoComplete="new-password"
                        placeholder={creating ? undefined : '•••••••• (leave blank to keep)'}
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              {canClear && (
                <label className="flex items-center gap-2 text-sm text-muted-foreground">
                  <Checkbox
                    checked={clear.includes(slot)}
                    onCheckedChange={(on) =>
                      form.setValue(
                        'clearSecrets',
                        on ? [...clear, slot] : clear.filter((x) => x !== slot),
                        { shouldDirty: true },
                      )
                    }
                  />
                  Remove the saved secret
                </label>
              )}
            </div>
          </FormRow>
        );
      })}
    </div>
  );
}
