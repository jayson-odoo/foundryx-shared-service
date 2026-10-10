import { describe, expect, it } from 'vitest';
import { ApiError } from '@/lib/api-client';
import type { ConnectorProductSettings, ConnectorTenantSettings } from '@/types/connector';
import {
  BLANK_PRODUCT,
  createProductSchema,
  fallbackHint,
  productFormSchema,
  productFormValues,
  serverFieldErrors,
  tenantFieldError,
  tenantFormValues,
  toProductInput,
  toTenantInput,
} from './connector-settings-schema';

const v = (value: string | null, source: 'database' | 'environment' | 'default' | 'unset') => ({ value, source });

const settings: ConnectorProductSettings = {
  key: 'acme',
  stored: true,
  status: 'ok',
  fields: {
    displayName: v('Acme DB', 'database'),
    connectionId: v('conn-acme', 'environment'),
    consentUrl: v('https://acme.test/c', 'environment'),
    apiBaseUrl: v('https://acme.test', 'database'),
    issuer: v('acme', 'default'),
    consentAudience: v('acme-connector-consent', 'default'),
    callAudience: v('acme-connector-api', 'default'),
  },
  secrets: {
    ssToProduct: { state: 'set', source: 'database' },
    productToSs: { state: 'set', source: 'environment' },
  },
};

describe('connector settings mapping (SETTINGS-IN-DB-SS)', () => {
  it('prefills only values saved here; fallbacks become placeholders; secrets blank', () => {
    const f = productFormValues(settings);
    expect(f.displayName).toBe('Acme DB');
    expect(f.apiBaseUrl).toBe('https://acme.test');
    expect(f.connectionId).toBe('');
    expect(f.issuer).toBe('');
    expect(f.ssToProductSecret).toBe('');
    expect(fallbackHint(settings, 'connectionId')).toBe('conn-acme');
    expect(fallbackHint(settings, 'displayName')).toBeUndefined();
  });

  it('toProductInput sends blanks as clears, omits blank secrets, drops a clear that is replaced', () => {
    const input = toProductInput({
      ...BLANK_PRODUCT,
      key: 'acme',
      displayName: ' Acme ',
      productToSsSecret: 'a-new-secret-value-1',
      clearSecrets: ['ssToProduct', 'productToSs'],
    });
    expect(input.displayName).toBe('Acme');
    expect(input.consentUrl).toBe('');
    expect(input.ssToProductSecret).toBeUndefined();
    expect(input.productToSsSecret).toBe('a-new-secret-value-1');
    expect(input.clearSecrets).toEqual(['ssToProduct']);
  });

  it('schema rejects bad urls, short or equal secrets, and bad keys on create', () => {
    const bad = productFormSchema.safeParse({ ...BLANK_PRODUCT, consentUrl: 'javascript:alert(1)' });
    expect(bad.success).toBe(false);
    expect(productFormSchema.safeParse({ ...BLANK_PRODUCT, ssToProductSecret: 'short' }).success).toBe(false);
    const same = 'same-secret-value-1234';
    expect(
      productFormSchema.safeParse({ ...BLANK_PRODUCT, ssToProductSecret: same, productToSsSecret: same }).success,
    ).toBe(false);
    expect(createProductSchema.safeParse({ ...BLANK_PRODUCT, key: 'Bad Key' }).success).toBe(false);
    expect(createProductSchema.safeParse({ ...BLANK_PRODUCT, key: 'delta' }).success).toBe(true);
  });

  it('tenant values: database prefill, blank -> null, ints converted', () => {
    const s = {
      publicBaseUrl: v('https://t.example', 'database'),
      allowedClientCidrs: v(null, 'unset'),
      redirectAllowlist: v('https://claude.ai/api/mcp/auth_callback', 'default'),
      manifestTtlSeconds: v('900', 'default'),
      callTimeoutSeconds: v('20', 'database'),
      callLogRetentionDays: v('180', 'environment'),
      forwardedForWarning: true,
    } as ConnectorTenantSettings;
    const f = tenantFormValues(s);
    expect(f.publicBaseUrl).toBe('https://t.example');
    expect(f.redirectAllowlist).toBe('');
    expect(toTenantInput({ ...f, manifestTtlSeconds: '60' })).toEqual({
      publicBaseUrl: 'https://t.example',
      allowedClientCidrs: null,
      redirectAllowlist: null,
      manifestTtlSeconds: 60,
      callTimeoutSeconds: 20,
      callLogRetentionDays: null,
    });
    expect(tenantFieldError('callTimeoutSeconds', '1.5')).toBe('Enter a whole number.');
    expect(tenantFieldError('publicBaseUrl', 'ftp://x')).toBe('Enter an http(s) URL.');
    expect(tenantFieldError('redirectAllowlist', 'https://ok.test, nope')).toMatch(/nope/);
    expect(tenantFieldError('allowedClientCidrs', '')).toBeNull();
  });

  it('serverFieldErrors reads the 422 fieldErrors body only', () => {
    const e = new ApiError('x', 422, null, { fieldErrors: { consentUrl: 'Enter an http(s) URL.' } });
    expect(serverFieldErrors(e)).toEqual({ consentUrl: 'Enter an http(s) URL.' });
    expect(serverFieldErrors(new ApiError('x', 409))).toBeNull();
    expect(serverFieldErrors(new Error('x'))).toBeNull();
  });
});
