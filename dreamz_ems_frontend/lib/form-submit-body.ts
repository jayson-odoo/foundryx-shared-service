/**
 * Build a form-submission request body (plan sprint-3/02 D12). When any answer
 * carries staged file uploads (`local:` placeholder keys backed by a live
 * `File`), send multipart: a `payload` JSON part ({answers, honeypot}) + one
 * `file:<fieldKey>` part per staged file. Otherwise plain JSON. Signatures ride
 * inside the JSON answers as data-URLs (the backend decodes + stores them), so
 * they never need a multipart part. Used by BOTH the internal and public submit.
 */
import { stagedFile } from '@/components/platform/form-renderer/file-input';
import type { FormAnswers } from '@/types/forms';

export interface SubmitBody {
  body: BodyInit;
  /** When true, the caller MUST NOT set a JSON Content-Type (the browser sets
   * the multipart boundary). `apiFetch`/`publicFetch` already skip it for
   * `FormData` bodies. */
  isMultipart: boolean;
}

export function buildSubmitBody(answers: FormAnswers, honeypot = ''): SubmitBody {
  const parts: { field: string; file: File }[] = [];
  for (const [field, value] of Object.entries(answers)) {
    if (!Array.isArray(value)) continue;
    for (const item of value) {
      if (
        item &&
        typeof item === 'object' &&
        typeof (item as { key?: unknown }).key === 'string' &&
        (item as { key: string }).key.startsWith('local:')
      ) {
        const file = stagedFile((item as { key: string }).key);
        if (file) parts.push({ field, file });
      }
    }
  }

  if (parts.length === 0) {
    return { body: JSON.stringify({ answers, honeypot }), isMultipart: false };
  }

  const fd = new FormData();
  fd.append('payload', JSON.stringify({ answers, honeypot }));
  for (const { field, file } of parts) fd.append(`file:${field}`, file, file.name);
  return { body: fd, isMultipart: true };
}
