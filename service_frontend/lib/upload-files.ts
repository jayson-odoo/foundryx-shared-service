import { shrinkImage } from '@/lib/shrink-image';

/** What a posted comment reports back when its files were uploaded after it. */
export interface CommentPostResult {
  commentId: string;
  /** Files that did NOT upload (the comment itself exists). */
  failed: File[];
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

/**
 * Upload files one after another (a big photo is shrunk first) and collect the
 * ones that failed, so the caller can name them and retry only those. Never
 * throws: a failure of one file does not stop the rest.
 */
export async function uploadInOrder(
  files: File[],
  upload: (file: File) => Promise<unknown>,
): Promise<File[]> {
  const failed: File[] = [];
  for (const file of files) {
    try {
      await upload(await shrinkImage(file));
    } catch {
      failed.push(file);
    }
  }
  return failed;
}
