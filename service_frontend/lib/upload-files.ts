import { ApiError } from '@/lib/api-client';
import { shrinkImage } from '@/lib/shrink-image';

/** A file that did not upload, with a plain-words reason to show next to it. */
export interface FailedUpload {
  file: File;
  reason: string;
}

/** What a posted comment reports back when its files were uploaded after it. */
export interface CommentPostResult {
  commentId: string;
  /** Files that did NOT upload (the comment itself exists). */
  failed: FailedUpload[];
}

export function isCommentPostResult(value: unknown): value is CommentPostResult {
  return (
    typeof value === 'object' &&
    value !== null &&
    !Array.isArray(value) &&
    Array.isArray((value as CommentPostResult).failed) &&
    typeof (value as CommentPostResult).commentId === 'string'
  );
}

/** Why an upload failed, in plain words. */
export function uploadFailureReason(name: string, err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 415) return `${name}: this file type can't be attached`;
    if (err.status === 413) return `${name} is too large (max 25 MB)`;
    if (err.status === 422 && err.message) return err.message;
    if (err.status === 429) return 'Too many uploads. Try again later.';
  }
  return `${name} did not upload`;
}

/**
 * Upload files one after another (a big photo is shrunk first) and collect the
 * ones that failed, so the caller can name them and retry only those. Never
 * throws: a failure of one file does not stop the rest.
 */
export async function uploadInOrder(
  files: File[],
  upload: (file: File) => Promise<unknown>,
): Promise<FailedUpload[]> {
  const failed: FailedUpload[] = [];
  for (const file of files) {
    try {
      await upload(await shrinkImage(file));
    } catch (err) {
      failed.push({ file, reason: uploadFailureReason(file.name, err) });
    }
  }
  return failed;
}
