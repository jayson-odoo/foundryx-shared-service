import { describe, expect, it } from 'vitest';
import {
  deriveTenantSlug,
  isReservedTenantSlug,
  isValidTenantSlug,
  RESERVED_TENANT_SLUGS,
  tenantUrl,
} from './tenant';

describe('isValidTenantSlug', () => {
  it('accepts lowercase kebab slugs', () => {
    expect(isValidTenantSlug('acme')).toBe(true);
    expect(isValidTenantSlug('acme-events')).toBe(true);
    expect(isValidTenantSlug('a1-b2-c3')).toBe(true);
  });

  it('rejects uppercase, spaces, symbols', () => {
    expect(isValidTenantSlug('Acme')).toBe(false);
    expect(isValidTenantSlug('acme events')).toBe(false);
    expect(isValidTenantSlug('acme_events')).toBe(false);
    expect(isValidTenantSlug('acme.events')).toBe(false);
  });

  it('rejects too-short, leading/trailing/double hyphen', () => {
    expect(isValidTenantSlug('ab')).toBe(false);
    expect(isValidTenantSlug('-acme')).toBe(false);
    expect(isValidTenantSlug('acme-')).toBe(false);
    expect(isValidTenantSlug('ac--me')).toBe(false);
  });

  it('rejects over 63 chars', () => {
    expect(isValidTenantSlug('a'.repeat(64))).toBe(false);
    expect(isValidTenantSlug('a'.repeat(63))).toBe(true);
  });
});

describe('isReservedTenantSlug', () => {
  it('flags every reserved slug', () => {
    for (const slug of RESERVED_TENANT_SLUGS) {
      expect(isReservedTenantSlug(slug)).toBe(true);
    }
  });

  it('passes normal slugs', () => {
    expect(isReservedTenantSlug('acme')).toBe(false);
  });
});

describe('deriveTenantSlug', () => {
  it('takes the first label of a 3-label host', () => {
    expect(deriveTenantSlug('acme.foundryxems.com')).toBe('acme');
  });

  it('strips the port', () => {
    expect(deriveTenantSlug('acme.foundryxems.com:3001')).toBe('acme');
  });

  it('falls back for localhost and IPs', () => {
    expect(deriveTenantSlug('localhost')).toBe('default');
    expect(deriveTenantSlug('localhost:3001')).toBe('default');
    expect(deriveTenantSlug('127.0.0.1')).toBe('default');
    expect(deriveTenantSlug('192.168.1.10')).toBe('default');
  });

  it('falls back for bare domains (no subdomain)', () => {
    expect(deriveTenantSlug('foundryxems.com')).toBe('default');
  });

  it('falls back for reserved infra subdomains', () => {
    expect(deriveTenantSlug('www.foundryxems.com')).toBe('default');
    expect(deriveTenantSlug('api.foundryxems.com')).toBe('default');
  });

  it('resolves <slug>.localhost dev hosts', () => {
    expect(deriveTenantSlug('acme.localhost:3001')).toBe('acme');
    expect(deriveTenantSlug('platform.localhost:3001')).toBe('platform');
  });

  it('platform/default subdomains resolve (real tenants, not infra aliases)', () => {
    expect(deriveTenantSlug('platform.foundryxems.com')).toBe('platform');
    expect(deriveTenantSlug('default.foundryxems.com')).toBe('default');
  });
});

describe('tenantUrl', () => {
  const loc = (host: string, protocol = 'http:') => ({ host, protocol }) as Location;

  it('swaps the subdomain on the operator host', () => {
    expect(tenantUrl('acme', loc('platform.localhost:3001'))).toBe(
      'http://acme.localhost:3001',
    );
    expect(tenantUrl('acme', loc('platform.foundryxems.com', 'https:'))).toBe(
      'https://acme.foundryxems.com',
    );
  });

  it('treats bare hosts as the base domain', () => {
    expect(tenantUrl('acme', loc('localhost:3001'))).toBe('http://acme.localhost:3001');
    expect(tenantUrl('acme', loc('foundryxems.com', 'https:'))).toBe(
      'https://acme.foundryxems.com',
    );
  });
});
