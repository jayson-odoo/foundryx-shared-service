import { z } from 'zod';
import { ApiError } from '@/lib/api-client';
import type {
  ConnectorProductCreateInput,
  ConnectorProductField,
  ConnectorProductSettings,
  ConnectorSecretSlot,
  ConnectorSettingSource,
  ConnectorTenantField,
  ConnectorTenantSettings,
  ConnectorTenantSettingsInput,
} from '@/types/connector';

/** Mirrors the backend key rule (`registry._KEY_RE`): it becomes the MCP URL. */
export const PRODUCT_KEY_RE = /^[a-z][a-z0-9_]{0,31}$/;
/** `products/new` is the create route, so `new` can never be a product key. */
export const RESERVED_KEYS = ['new'];
export const MIN_SECRET_LEN = 16;

export const PRODUCT_FIELDS: ConnectorProductField[] = [
  'displayName',
  'connectionId',
  'consentUrl',
  'apiBaseUrl',
  'issuer',
  'consentAudience',
  'callAudience',
];

export const TENANT_FIELDS: ConnectorTenantField[] = [
  'publicBaseUrl',
  'allowedClientCidrs',
  'redirectAllowlist',
  'manifestTtlSeconds',
  'callTimeoutSeconds',
  'callLogRetentionDays',
];

export const TENANT_INT_FIELDS: ConnectorTenantField[] = [
  'manifestTtlSeconds',
  'callTimeoutSeconds',
  'callLogRetentionDays',
];

export const SOURCE_LABELS: Record<ConnectorSettingSource, string> = {
  database: 'Saved here',
  environment: 'Environment',
  default: 'Default',
  unset: 'Not set',
  unreadable: 'Unreadable',
};

export function isHttpUrl(value: string): boolean {
  try {
    const u = new URL(value);
    return (u.protocol === 'http:' || u.protocol === 'https:') && !!u.hostname && !/\s/.test(value);
  } catch {
    return false;
  }
}

const optionalUrl = z
  .string()
  .trim()
  .refine((v) => v === '' || isHttpUrl(v), 'Enter an http(s) URL.');

const optionalSecret = z
  .string()
  .trim()
  .refine((v) => v === '' || v.length >= MIN_SECRET_LEN, `Use at least ${MIN_SECRET_LEN} characters.`);

export const productFormSchema = z
  .object({
    key: z.string().trim(),
    displayName: z.string().trim().max(120, 'At most 120 characters.'),
    connectionId: z.string().trim().max(128, 'At most 128 characters.'),
    consentUrl: optionalUrl,
    apiBaseUrl: optionalUrl,
    issuer: z.string().trim().max(128, 'At most 128 characters.'),
    consentAudience: z.string().trim().max(128, 'At most 128 characters.'),
    callAudience: z.string().trim().max(128, 'At most 128 characters.'),
    ssToProductSecret: optionalSecret,
    productToSsSecret: optionalSecret,
    clearSecrets: z.array(z.enum(['ssToProduct', 'productToSs'])),
  })
  .superRefine((v, ctx) => {
    if (v.ssToProductSecret && v.ssToProductSecret === v.productToSsSecret) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ['productToSsSecret'],
        message: 'Must differ from the secret to the product.',
      });
    }
  });

export type ProductFormValues = z.infer<typeof productFormSchema>;

export const createProductSchema = productFormSchema.superRefine((v, ctx) => {
  if (!PRODUCT_KEY_RE.test(v.key) || RESERVED_KEYS.includes(v.key)) {
    ctx.addIssue({
      code: z.ZodIssueCode.custom,
      path: ['key'],
      message: 'Lowercase letters, digits and _, starting with a letter (max 32).',
    });
  }
});

export const BLANK_PRODUCT: ProductFormValues = {
  key: '',
  displayName: '',
  connectionId: '',
  consentUrl: '',
  apiBaseUrl: '',
  issuer: '',
  consentAudience: '',
  callAudience: '',
  ssToProductSecret: '',
  productToSsSecret: '',
  clearSecrets: [],
};

/**
 * Edit prefill: only values SAVED HERE go into the inputs. A field inherited
 * from the environment or a default stays blank (its effective value is the
 * input's placeholder), so saving without touching it keeps the fallback.
 * Secrets always start blank (blank = keep).
 */
export function productFormValues(s: ConnectorProductSettings): ProductFormValues {
  const out: ProductFormValues = { ...BLANK_PRODUCT, key: s.key };
  for (const f of PRODUCT_FIELDS) {
    const v = s.fields[f];
    out[f] = v && v.source === 'database' ? (v.value ?? '') : '';
  }
  return out;
}

/** Placeholder for a field left blank: what it falls back to. */
export function fallbackHint(
  s: ConnectorProductSettings | null,
  field: ConnectorProductField,
): string | undefined {
  const v = s?.fields[field];
  if (!v || v.source === 'database' || !v.value) return undefined;
  return v.value;
}

export function toProductInput(values: ProductFormValues): ConnectorProductCreateInput {
  const input: ConnectorProductCreateInput = { key: values.key.trim() };
  for (const f of PRODUCT_FIELDS) input[f] = values[f].trim();
  if (values.ssToProductSecret.trim()) input.ssToProductSecret = values.ssToProductSecret.trim();
  if (values.productToSsSecret.trim()) input.productToSsSecret = values.productToSsSecret.trim();
  const clear = values.clearSecrets.filter(
    (slot: ConnectorSecretSlot) =>
      !(slot === 'ssToProduct' ? input.ssToProductSecret : input.productToSsSecret),
  );
  if (clear.length) input.clearSecrets = clear;
  return input;
}

// --- tenant-level (Access tab) ---------------------------------------------------------

export type TenantFormValues = Record<ConnectorTenantField, string>;

export function tenantFormValues(s: ConnectorTenantSettings): TenantFormValues {
  const out = {} as TenantFormValues;
  for (const f of TENANT_FIELDS) {
    const v = s[f];
    out[f] = v.source === 'database' ? (v.value ?? '') : '';
  }
  return out;
}

export function tenantFieldError(field: ConnectorTenantField, raw: string): string | null {
  const v = raw.trim();
  if (!v) return null;
  if (TENANT_INT_FIELDS.includes(field)) {
    if (!/^\d+$/.test(v)) return 'Enter a whole number.';
    return null;
  }
  if (field === 'publicBaseUrl' && !isHttpUrl(v)) return 'Enter an http(s) URL.';
  if (field === 'redirectAllowlist') {
    const bad = v
      .split(',')
      .map((x) => x.trim())
      .filter(Boolean)
      .find((x) => !isHttpUrl(x));
    if (bad) return `${bad} is not an http(s) URL.`;
  }
  return null;
}

/** '' clears the saved value (back to environment/default). */
export function toTenantInput(values: TenantFormValues): ConnectorTenantSettingsInput {
  const input: ConnectorTenantSettingsInput = {};
  for (const f of TENANT_FIELDS) {
    const v = values[f].trim();
    if (TENANT_INT_FIELDS.includes(f)) {
      (input as Record<string, number | null>)[f] = v === '' ? null : Number(v);
    } else {
      (input as Record<string, string | null>)[f] = v === '' ? null : v;
    }
  }
  return input;
}

/** The backend's 422 `{fieldErrors}` body, or null for any other failure. */
export function serverFieldErrors(e: unknown): Record<string, string> | null {
  if (!(e instanceof ApiError) || e.status !== 422) return null;
  const detail = e.detail as { fieldErrors?: Record<string, string> } | undefined;
  return detail && detail.fieldErrors ? detail.fieldErrors : null;
}
