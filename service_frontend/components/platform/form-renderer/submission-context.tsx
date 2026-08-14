'use client';

/** Read-mode submission context (sprint-3/02) - gives FieldRead the submission
 * id so uploaded-file chips can fetch the authed, CSP-sandboxed serve route and
 * open the blob (an <a href> can't carry the Bearer). Absent in fill/preview.
 *
 * `fetchFile` is INJECTED by the page (Cluster E portal-signout fix): the staff
 * surfaces supply the staff `apiFetchBlob`, the portal supplies a Profile-session
 * blob fetcher. The renderer must NOT statically import the staff client - that
 * would 401 a Profile JWT and sign the portal session out. No fetcher → the chip
 * renders as a plain (non-clickable) label. */
import { createContext, useContext } from 'react';

export type FileBlobFetcher = (path: string) => Promise<Blob>;

export const SubmissionContext = createContext<{
  submissionId?: string;
  fetchFile?: FileBlobFetcher;
}>({});

export function useSubmissionId(): string | undefined {
  return useContext(SubmissionContext).submissionId;
}

export function useFileFetcher(): FileBlobFetcher | undefined {
  return useContext(SubmissionContext).fetchFile;
}
