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
  /** Secret provider fields — write-only; blank on edit = keep existing. */
  credentials: z.record(z.string()),
});

export type ConnectionFormValues = z.infer<typeof connectionFormSchema>;

export function isSecretField(f: ProviderField): boolean {
  return Boolean(f.secret);
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

/** Values prefilled from an existing connection (secrets stay blank = keep). */
export function valuesForConnection(
  provider: IntegrationProvider,
  connection: { provider: string; name: string; config: Record<string, string> },
): ConnectionFormValues {
  const config: Record<string, string> = {};
  // Secrets prefill as '' (NOT absent) — a registered-but-undefined value
  // fails z.record(z.string()) with a bare "Required", breaking the
  // blank-to-keep contract on edit.
  const credentials: Record<string, string> = {};
  for (const f of provider.fields) {
    if (isSecretField(f)) credentials[f.key] = '';
    else config[f.key] = connection.config[f.key] ?? '';
  }
  return { provider: connection.provider, name: connection.name, config, credentials };
}

/**
 * Per-provider required validation (plan 06 D6): config required-fields must
 * be non-empty always; secret required-fields only when CREATING — on edit a
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

/** The write payload — only NON-EMPTY secrets travel (blank = keep). */
export function toConnectionInput(values: ConnectionFormValues): {
  provider: string;
  name: string;
  config: Record<string, string>;
  credentials: Record<string, string>;
} {
  const credentials: Record<string, string> = {};
  for (const [key, value] of Object.entries(values.credentials)) {
    if (value.trim()) credentials[key] = value;
  }
  return {
    provider: values.provider,
    name: values.name,
    config: { ...values.config },
    credentials,
  };
}
