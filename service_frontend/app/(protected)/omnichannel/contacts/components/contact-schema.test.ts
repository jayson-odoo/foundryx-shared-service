import { describe, expect, it } from 'vitest';
import { contactCreateSchema, defaultContactCreateValues } from './contact-schema';

/**
 * Create-contact schema (AC-CTM-08/46) - `phone` is required and create-only
 * (D-A2-4); every other client-visible field is a plain string capped at the
 * backend's own limits (`ContactProfileService`'s validators, mirrored here
 * so a bad value never round-trips to a 422 the user never sees inline).
 */
describe('contactCreateSchema', () => {
  it('defaults every field to an empty/neutral value (no lifecycle pre-picked)', () => {
    const values = defaultContactCreateValues();
    expect(values).toEqual({
      firstName: '',
      lastName: '',
      phone: '',
      email: '',
      language: '',
      countryCode: '',
      lifecycleStatusId: null,
      tagIds: [],
    });
  });

  it('rejects a blank phone - the ONLY required field', () => {
    const result = contactCreateSchema.safeParse({ ...defaultContactCreateValues(), phone: '' });
    expect(result.success).toBe(false);
    if (!result.success) {
      expect(result.error.flatten().fieldErrors.phone?.[0]).toBe('Phone is required.');
    }
  });

  it('rejects a whitespace-only phone (trimmed before the min-length check)', () => {
    const result = contactCreateSchema.safeParse({ ...defaultContactCreateValues(), phone: '   ' });
    expect(result.success).toBe(false);
  });

  it('accepts a plain phone value with every other field left blank', () => {
    const result = contactCreateSchema.safeParse({ ...defaultContactCreateValues(), phone: '+60123456789' });
    expect(result.success).toBe(true);
  });

  it('caps countryCode at 2 characters (ISO-3166 alpha-2)', () => {
    const result = contactCreateSchema.safeParse({
      ...defaultContactCreateValues(),
      phone: '+60123456789',
      countryCode: 'MYS',
    });
    expect(result.success).toBe(false);
    if (!result.success) {
      expect(result.error.flatten().fieldErrors.countryCode?.[0]).toBe('Use a 2-letter code.');
    }
  });

  it('caps firstName/lastName at 120 characters', () => {
    const tooLong = 'a'.repeat(121);
    const result = contactCreateSchema.safeParse({
      ...defaultContactCreateValues(),
      phone: '+60123456789',
      firstName: tooLong,
    });
    expect(result.success).toBe(false);
    if (!result.success) {
      expect(result.error.flatten().fieldErrors.firstName?.[0]).toBe('Too long.');
    }
  });

  it('accepts an explicit lifecycleStatusId and a populated tagIds list', () => {
    const result = contactCreateSchema.safeParse({
      ...defaultContactCreateValues(),
      phone: '+60123456789',
      lifecycleStatusId: 'st-1',
      tagIds: ['tag-1', 'tag-2'],
    });
    expect(result.success).toBe(true);
  });
});
