import { describe, expect, it } from 'vitest';
import { userFormSchema } from './user-schema';

const valid = { name: 'Jane Doe', email: 'jane@foundryx.io', roleIds: ['r1'], status: 'ACTIVE' as const };

describe('userFormSchema', () => {
  it('accepts a valid user', () => {
    expect(userFormSchema.safeParse(valid).success).toBe(true);
  });

  it('rejects an empty name', () => {
    expect(userFormSchema.safeParse({ ...valid, name: '   ' }).success).toBe(false);
  });

  it('rejects an invalid email', () => {
    expect(userFormSchema.safeParse({ ...valid, email: 'not-an-email' }).success).toBe(false);
  });

  it('rejects an unknown status', () => {
    expect(userFormSchema.safeParse({ ...valid, status: 'INVITED' }).success).toBe(false);
  });

  it('allows no roles', () => {
    expect(userFormSchema.safeParse({ ...valid, roleIds: [] }).success).toBe(true);
  });
});
