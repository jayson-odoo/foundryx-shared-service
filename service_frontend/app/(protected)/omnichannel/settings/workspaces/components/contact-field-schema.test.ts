import { describe, expect, it } from 'vitest';
import { contactFieldSchema, slugifyFieldKey } from './contact-field-schema';

describe('slugifyFieldKey', () => {
  it('derives a camelCase key from a label', () => {
    expect(slugifyFieldKey('Lead Source')).toBe('leadSource');
    expect(slugifyFieldKey('VIP status')).toBe('vipStatus');
  });

  it('strips non-alphanumeric separators', () => {
    expect(slugifyFieldKey('Renewal Date (approx)')).toBe('renewalDateApprox');
  });

  it('drops a leading non-letter from the first word', () => {
    expect(slugifyFieldKey('2nd Contact')).toBe('ndContact');
  });

  it('caps at 40 characters', () => {
    const long = slugifyFieldKey('This is a very very very very long field label indeed');
    expect(long.length).toBeLessThanOrEqual(40);
  });

  it('returns empty for a label with no letters', () => {
    expect(slugifyFieldKey('123')).toBe('');
  });
});

describe('contactFieldSchema', () => {
  const base = {
    label: 'Lead Source',
    key: 'leadSource',
    description: '',
    type: 'text' as const,
    options: [] as string[],
    visibility: 'always' as const,
  };

  it('accepts a valid text field', () => {
    expect(contactFieldSchema.safeParse(base).success).toBe(true);
  });

  it('rejects a blank name', () => {
    const r = contactFieldSchema.safeParse({ ...base, label: '  ' });
    expect(r.success).toBe(false);
  });

  it('rejects a key with an invalid shape (must start lowercase letter)', () => {
    const r = contactFieldSchema.safeParse({ ...base, key: 'Lead-Source' });
    expect(r.success).toBe(false);
  });

  it('rejects a reserved system-field key', () => {
    const r = contactFieldSchema.safeParse({ ...base, key: 'firstName' });
    expect(r.success).toBe(false);
  });

  it('requires at least one non-blank option for a list field', () => {
    const empty = contactFieldSchema.safeParse({ ...base, type: 'list', options: [] });
    expect(empty.success).toBe(false);

    const blankOnly = contactFieldSchema.safeParse({ ...base, type: 'list', options: ['   '] });
    expect(blankOnly.success).toBe(false);

    const ok = contactFieldSchema.safeParse({ ...base, type: 'list', options: ['Referral', 'Website'] });
    expect(ok.success).toBe(true);
  });

  it('does not require options for a non-list type', () => {
    const r = contactFieldSchema.safeParse({ ...base, type: 'checkbox', options: [] });
    expect(r.success).toBe(true);
  });
});
