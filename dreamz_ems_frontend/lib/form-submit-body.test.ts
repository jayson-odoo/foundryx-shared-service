import { describe, expect, it, vi } from 'vitest';

// Stub the file registry: only `local:1` resolves to a live File.
vi.mock('@/components/platform/form-renderer/file-input', () => ({
  stagedFile: (key: string) =>
    key === 'local:1' ? new File(['x'], 'a.png', { type: 'image/png' }) : undefined,
}));

import { buildSubmitBody } from './form-submit-body';

describe('buildSubmitBody (sprint-3/02 D12)', () => {
  it('sends JSON when there are no staged files', () => {
    const { body, isMultipart } = buildSubmitBody({ name: 'Ada' }, '');
    expect(isMultipart).toBe(false);
    expect(JSON.parse(body as string)).toEqual({ answers: { name: 'Ada' }, honeypot: '' });
  });

  it('sends multipart with a file:<field> part when a file field has uploads', () => {
    const answers = { resume: [{ key: 'local:1', name: 'a.png', size: 1, mime: 'image/png' }] };
    const { body, isMultipart } = buildSubmitBody(answers, '');
    expect(isMultipart).toBe(true);
    expect(body).toBeInstanceOf(FormData);
    const fd = body as FormData;
    expect(typeof fd.get('payload')).toBe('string');
    expect(fd.get('file:resume')).toBeInstanceOf(File);
  });

  it('keeps signatures in the JSON body (no multipart part)', () => {
    const { isMultipart } = buildSubmitBody({ sign: 'data:image/png;base64,AAAA' }, '');
    expect(isMultipart).toBe(false);
  });

  it('carries the honeypot value', () => {
    const { body } = buildSubmitBody({ name: 'A' }, 'bot');
    expect(JSON.parse(body as string).honeypot).toBe('bot');
  });
});
