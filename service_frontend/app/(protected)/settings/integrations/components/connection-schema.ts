import { z } from 'zod';
import type { IntegrationProvider, ProviderField } from '@/types/integration';

/**
 * RHF values for the connection form. Provider fields are dynamic, so the
 * static schema only pins the always-present shape; per-provider REQUIRED
 * checks run in `requiredFieldErrors` at save time (the provider isn't known
 * until picked).
 */
export const connectionFormSchema = z.object({
  provider: z.string().min(1, 'Pick a provider.'),
  name: z.string().min(1, 'Name is required.'),
  /** Non-secret provider fields (config_json). */
  config: z.record(z.string()),
  /** Secret provider fields - write-only; blank on edit = keep existing. */
  credentials: z.record(z.string()),
});

export type ConnectionFormValues = z.infer<typeof connectionFormSchema>;

export function isSecretField(f: ProviderField): boolean {
  return Boolean(f.secret);
}

/**
 * Whether a field is currently shown, per its `showWhen` (plan sprint-5/08,
 * D11) - absent = always shown. `config` is whatever holds the DRIVER
 * field's live value: the edit form's live values, or a read-mode
 * connection's stored config (`storedOrEffective` resolves legacy/effective
 * values the same way the driven field's own read-mode row does).
 */
export function isFieldVisible(f: ProviderField, config: Record<string, string>): boolean {
  if (!f.showWhen) return true;
  const value = config[f.showWhen.field] ?? '';
  return f.showWhen.values.includes(value);
}

/** Default form values for a freshly-picked provider (field defaults applied). */
export function defaultsForProvider(provider: IntegrationProvider): ConnectionFormValues {
  const config: Record<string, string> = {};
  const credentials: Record<string, string> = {};
  for (const f of provider.fields) {
    if (isSecretField(f)) credentials[f.key] = '';
    else config[f.key] = f.defaultValue ?? '';
  }
  return { provider: provider.provider, name: provider.title, config, credentials };
}

/**
 * Registry-driven dependent default (`ProviderField.defaultsFrom`, plan 22
 * AC-22-04): the value a field should take after its driver select changed,
 * or null when nothing should change - because the field has no dependency,
 * the choice has no mapped default, or the operator typed a custom value
 * (anything that is neither blank nor one of the stock defaults is theirs).
 */
export function dependentDefault(
  f: ProviderField,
  driverValue: string,
  current: string,
): string | null {
  if (!f.defaultsFrom) return null;
  const next = f.defaultsFrom.values[driverValue];
  if (next === undefined || next === current) return null;
  const stock = new Set(Object.values(f.defaultsFrom.values));
  if (current.trim() !== '' && !stock.has(current)) return null;
  return next;
}

/**
 * The Sorento connection's contract-version select
 * (`modules/autocount/sorento_provider.py`, `fix/sorento-contract-version-field`):
 * a connection saved BEFORE the field existed has no stored value, and the
 * sink then runs at contract 1. On edit that field prefills with that
 * EFFECTIVE value, not blank: a blank required select would silently block
 * every unrelated save of the connection, while "1" states the runtime truth
 * without flipping anything - the operator still has to pick 2 explicitly.
 * Scoped to this one key on purpose; every other field keeps the plain
 * "stored value or blank" prefill (no new generic behaviour).
 */
export const SORENTO_CONTRACT_VERSION_KEY = 'sorentoContractVersion';
const SORENTO_CONTRACT_VERSION_EFFECTIVE = '1';

/** The value a field SHOWS for an existing connection: the stored one, else
 *  the field's own `effectiveValue` (feat/sink-concurrency-ui - the provider
 *  computes it per request, e.g. the platform's `sinkConcurrency` default),
 *  else the Sorento contract-version literal above (its provider payload
 *  predates `effectiveValue` and still hardcodes "1"), else blank. Used by
 *  both the edit prefill and the read-mode row so the two modes never
 *  disagree about what the connection runs at. */
export function storedOrEffective(f: ProviderField, config: Record<string, string>): string {
  const stored = config[f.key];
  if (stored !== undefined) return stored;
  if (f.effectiveValue !== undefined) return f.effectiveValue;
  return f.key === SORENTO_CONTRACT_VERSION_KEY ? SORENTO_CONTRACT_VERSION_EFFECTIVE : '';
}

/** Values prefilled from an existing connection (secrets stay blank = keep). */
export function valuesForConnection(
  provider: IntegrationProvider,
  connection: { provider: string; name: string; config: Record<string, string> },
): ConnectionFormValues {
  const config: Record<string, string> = {};
  // Secrets prefill as '' (NOT absent) - a registered-but-undefined value
  // fails z.record(z.string()) with a bare "Required", breaking the
  // blank-to-keep contract on edit.
  const credentials: Record<string, string> = {};
  for (const f of provider.fields) {
    if (isSecretField(f)) credentials[f.key] = '';
    else config[f.key] = storedOrEffective(f, connection.config);
  }
  return { provider: connection.provider, name: connection.name, config, credentials };
}

/**
 * Per-provider required validation (plan 06 D6): config required-fields must
 * be non-empty always; secret required-fields only when CREATING - on edit a
 * blank secret means "keep the stored one" (write-only contract).
 */
export function requiredFieldErrors(
  provider: IntegrationProvider,
  values: ConnectionFormValues,
  creating: boolean,
): { path: `config.${string}` | `credentials.${string}`; message: string }[] {
  const errors: { path: `config.${string}` | `credentials.${string}`; message: string }[] = [];
  for (const f of provider.fields) {
    if (!f.required) continue;
    // A hidden field (`showWhen` unmet) is dropped from the required set -
    // AppId/user/password are not required when Auth = "none" (AC-08-04).
    if (!isFieldVisible(f, values.config)) continue;
    if (isSecretField(f)) {
      if (creating && !(values.credentials[f.key] ?? '').trim()) {
        errors.push({ path: `credentials.${f.key}`, message: `${f.label} is required.` });
      }
    } else if (!(values.config[f.key] ?? '').trim()) {
      errors.push({ path: `config.${f.key}`, message: `${f.label} is required.` });
    }
  }
  return errors;
}

/**
 * The write payload - only NON-EMPTY secrets travel (blank = keep). `provider`
 * (optional, plan sprint-5/08 AC-08-04) drops any field whose `showWhen` is
 * unmet from BOTH `config` and `credentials` - a hidden field never reaches
 * the wire, so a stale AppId/password left over from switching Auth to "none"
 * is never silently saved. Omitted `provider` = every value travels
 * (pre-`showWhen` callers, and providers with no conditional fields at all).
 */
export function toConnectionInput(
  values: ConnectionFormValues,
  provider?: IntegrationProvider | null,
): {
  provider: string;
  name: string;
  config: Record<string, string>;
  credentials: Record<string, string>;
} {
  const fieldByKey = new Map((provider?.fields ?? []).map((f) => [f.key, f]));
  const visible = (key: string) => {
    const f = fieldByKey.get(key);
    return !f || isFieldVisible(f, values.config);
  };
  const credentials: Record<string, string> = {};
  for (const [key, value] of Object.entries(values.credentials)) {
    if (value.trim() && visible(key)) credentials[key] = value;
  }
  const config: Record<string, string> = {};
  for (const [key, value] of Object.entries(values.config)) {
    if (visible(key)) config[key] = value;
  }
  return {
    provider: values.provider,
    name: values.name,
    config,
    credentials,
  };
}
