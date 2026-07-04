import { describe, expect, it } from 'vitest';
import { RateLimitError } from '@/lib/service-errors';
import { FormSubmitError } from './form-service';
import { mockPublicFormService } from './public-form-service.mock';

describe('public form service mock (sprint-3/02)', () => {
  it('returns null for an unknown form (uniform 404)', async () => {
    expect(await mockPublicFormService.view('acme', 'missing-x')).toBeNull();
  });

  it('open form carries its definition + honeypot field', async () => {
    const view = await mockPublicFormService.view('acme', 'reg');
    expect(view?.state).toBe('open');
    expect(view?.definition).toBeTruthy();
    expect(view?.honeypotField).toBeTruthy();
  });

  it('closed/full forms hide the definition + carry a message', async () => {
    const closed = await mockPublicFormService.view('acme', 'closed-x');
    expect(closed?.state).toBe('closed');
    expect(closed?.definition).toBeNull();
    expect(closed?.message).toBeTruthy();
    const full = await mockPublicFormService.view('acme', 'full-x');
    expect(full?.state).toBe('full');
  });

  it('a tripped honeypot rejects as a submit error (silent drop)', async () => {
    await expect(
      mockPublicFormService.submit('acme', 'reg', { answers: { email: 'a@b.com' }, honeypot: 'ACME' }),
    ).rejects.toBeInstanceOf(FormSubmitError);
  });

  it('maps a throttle to RateLimitError', async () => {
    await expect(
      mockPublicFormService.submit('acme', '429-x', { answers: { email: 'a@b.com' }, honeypot: '' }),
    ).rejects.toBeInstanceOf(RateLimitError);
  });

  it('surfaces a per-field validation error', async () => {
    await expect(
      mockPublicFormService.submit('acme', 'reg', { answers: {}, honeypot: '' }),
    ).rejects.toBeInstanceOf(FormSubmitError);
  });
});
