import { beforeEach, describe, expect, it } from 'vitest';
import {
  EmailTakenError,
  InvalidPasswordError,
  InvalidTokenError,
  RateLimitError,
} from './email-change-service';
import {
  __resetMockEmailChange,
  mockEmailChangeService as svc,
} from './email-change-service.mock';

describe('email-change mock service (ceremony contract)', () => {
  beforeEach(() => __resetMockEmailChange());

  it('starts with no pending request', async () => {
    expect(await svc.getPending()).toBeNull();
  });

  it('request creates a PENDING_OLD row with the normalized address', async () => {
    const pending = await svc.request('New.Person@Example.com', 'Demo1234!');
    expect(pending.status).toBe('PENDING_OLD');
    expect(pending.newEmail).toBe('new.person@example.com');
    expect(await svc.getPending()).toEqual(pending);
  });

  it('re-request replaces the prior outstanding request', async () => {
    await svc.request('first@example.com', 'Demo1234!');
    await svc.request('second@example.com', 'Demo1234!');
    const pending = await svc.getPending();
    expect(pending?.newEmail).toBe('second@example.com');
  });

  it('rejects a wrong password without creating a request', async () => {
    await expect(svc.request('new@example.com', 'wrongpass')).rejects.toBeInstanceOf(
      InvalidPasswordError,
    );
    expect(await svc.getPending()).toBeNull();
  });

  it('throttles request (429 knob)', async () => {
    await expect(
      svc.request('throttled@example.com', 'Demo1234!'),
    ).rejects.toBeInstanceOf(RateLimitError);
  });

  it('cancel clears the pending request', async () => {
    await svc.request('new@example.com', 'Demo1234!');
    await svc.cancel();
    expect(await svc.getPending()).toBeNull();
  });

  it('approve moves the request to PENDING_NEW', async () => {
    await svc.request('new@example.com', 'Demo1234!');
    await svc.approve('good-token');
    expect((await svc.getPending())?.status).toBe('PENDING_NEW');
  });

  it('verify completes the ceremony (pending row gone)', async () => {
    await svc.request('new@example.com', 'Demo1234!');
    await svc.approve('good-token');
    await svc.verify('good-token');
    expect(await svc.getPending()).toBeNull();
  });

  it.each(['', 'expired-abc', 'used-abc'])(
    'rejects bad token %j on approve and verify',
    async (token) => {
      await expect(svc.approve(token)).rejects.toBeInstanceOf(InvalidTokenError);
      await expect(svc.verify(token)).rejects.toBeInstanceOf(InvalidTokenError);
    },
  );

  it('throttles token redeems (429 knob)', async () => {
    await expect(svc.approve('throttled-abc')).rejects.toBeInstanceOf(RateLimitError);
    await expect(svc.verify('throttled-abc')).rejects.toBeInstanceOf(RateLimitError);
  });

  it('verify surfaces the uniqueness race as EmailTakenError', async () => {
    await expect(svc.verify('taken-abc')).rejects.toBeInstanceOf(EmailTakenError);
  });
});
