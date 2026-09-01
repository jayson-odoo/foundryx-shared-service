import { describe, expect, it } from 'vitest';
import { tenantProvisionSchema, tenantUpdateSchema } from './tenant-schema';

const validProvision = {
  name: 'Acme Events',
  slug: 'acme-events',
  contactName: 'Kay Meister',
  contactEmail: 'kay@acme.test',
  customDomain: '',
  notes: '',
  adminName: 'Kay Meister',
  adminEmail: 'kay@acme.test',
  adminPassword: 'ChangeMe1!',
};

describe('tenantProvisionSchema', () => {
  it('accepts a valid provision payload', () => {
    expect(tenantProvisionSchema.safeParse(validProvision).success).toBe(true);
  });

  it('requires a name', () => {
    expect(tenantProvisionSchema.safeParse({ ...validProvision, name: '  ' }).success).toBe(false);
  });

  it('rejects an invalid slug', () => {
    expect(tenantProvisionSchema.safeParse({ ...validProvision, slug: 'Acme!' }).success).toBe(false);
    expect(tenantProvisionSchema.safeParse({ ...validProvision, slug: 'ab' }).success).toBe(false);
  });

  it('rejects a reserved slug', () => {
    for (const slug of ['platform', 'admin', 'www', 'default']) {
      expect(tenantProvisionSchema.safeParse({ ...validProvision, slug }).success).toBe(false);
    }
  });

  it('requires the first-admin block', () => {
    expect(
      tenantProvisionSchema.safeParse({ ...validProvision, adminName: '' }).success,
    ).toBe(false);
    expect(
      tenantProvisionSchema.safeParse({ ...validProvision, adminEmail: 'not-an-email' }).success,
    ).toBe(false);
    expect(
      tenantProvisionSchema.safeParse({ ...validProvision, adminPassword: 'short' }).success,
    ).toBe(false);
  });

  it('caps the password at 72 chars (bcrypt)', () => {
    expect(
      tenantProvisionSchema.safeParse({ ...validProvision, adminPassword: 'x'.repeat(73) }).success,
    ).toBe(false);
  });
});

describe('tenantUpdateSchema', () => {
  it('accepts empty admin block + arbitrary (immutable) slug', () => {
    const r = tenantUpdateSchema.safeParse({
      ...validProvision,
      slug: 'platform', // read-only display value - not re-validated on update
      adminName: '',
      adminEmail: '',
      adminPassword: '',
    });
    expect(r.success).toBe(true);
  });

  it('still validates contact email when present', () => {
    expect(
      tenantUpdateSchema.safeParse({ ...validProvision, contactEmail: 'nope' }).success,
    ).toBe(false);
  });
});
