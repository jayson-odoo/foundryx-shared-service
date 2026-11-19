/**
 * One Jobs place (Foundryx UIUX switch only, slice W3-JOBS): the four kinds of
 * background work SS tracks today (uploads, imports, background jobs and ZIP
 * downloads) as one list of jobs, each with what it is and for what, a status
 * chip, real progress while it runs ("820 of 1,240") and its one next step.
 *
 * Pure: the providers keep owning the data, the polling and every request; this
 * only says how a row reads. With the switch off nothing imports it.
 */
import type { DownloadJob, UploadFileItem } from '@/types/documents';
import type { ImportJob } from '@/types/import';
import { JOB_IN_FLIGHT, type Job } from '@/types/jobs';
import { jobTypeLabel } from './job-display';

export type FxJobKind = 'upload' | 'import' | 'job' | 'download';

/** The chip's words and colour set: `ok` done, `warn` act on it, `bad`
 *  failed, `run` working, `neutral` anything else. */
export type FxJobTone = 'ok' | 'warn' | 'bad' | 'run' | 'neutral';

/** Where a job is: still working, waiting for the user, or over. */
export type FxJobPhase = 'running' | 'waiting' | 'ended';

export type FxJobStep =
  | { kind: 'download'; label: 'Download' }
  | { kind: 'retry-upload'; label: 'Try again' }
  | { kind: 'resolve-upload'; label: 'Keep both' | 'Replace'; mode: 'keep_both' | 'replace' }
  | { kind: 'open'; label: string };

export interface FxJobItem {
  key: string;
  id: string;
  kind: FxJobKind;
  /** "Import · Users", "Storage migration", "Upload · invoice.pdf". */
  title: string;
  status: string;
  tone: FxJobTone;
  phase: FxJobPhase;
  /** Real progress while it runs, from the server's (or the browser's) count. */
  progress?: { done: number; total: number; text: string; pct: number };
  /** One quiet line: counts, size or the time it started. */
  detail?: string;
  /** Moment for the detail line, formatted by the caller. */
  at?: string;
  error?: string;
  /** The job's own page, when it has one. */
  href?: string;
  /** Next steps, as text buttons (at most two, the safer first). */
  steps: FxJobStep[];
  /** Sort key: ISO time, newest first; uploads (this session) go on top. */
  sortAt: string;
}

const NUM = new Intl.NumberFormat('en-US');
export const fmtCount = (n: number): string => NUM.format(n);

function pct(done: number, total: number): number {
  if (total <= 0) return 0;
  return Math.min(100, Math.round((done / total) * 100));
}

/** "project_participant" -> "Project participant". */
export function humanizeKey(key: string): string {
  const words = key.replace(/[_-]+/g, ' ').trim();
  return words ? words[0].toUpperCase() + words.slice(1) : key;
}

function plural(n: number, one: string, many = `${one}s`): string {
  return `${fmtCount(n)} ${n === 1 ? one : many}`;
}

// ── Background jobs (storage migration and future types) ────────────────

export function jobItem(job: Job): FxJobItem {
  const failed = job.progressFailed;
  const base = {
    key: `job:${job.id}`,
    id: job.id,
    kind: 'job' as const,
    title: jobTypeLabel(job.type),
    href: `/jobs/${job.id}`,
    sortAt: job.createdAt,
    at: job.createdAt,
    error: job.error ?? undefined,
    steps: [] as FxJobStep[],
  };
  const progress =
    JOB_IN_FLIGHT.has(job.status) && job.progressTotal > 0
      ? {
          done: job.progressDone,
          total: job.progressTotal,
          pct: pct(job.progressDone, job.progressTotal),
          text: `${fmtCount(job.progressDone)} of ${fmtCount(job.progressTotal)}${
            failed ? ` · ${fmtCount(failed)} failed` : ''
          }`,
        }
      : undefined;
  const counts =
    job.progressTotal > 0
      ? `${fmtCount(job.progressDone)} of ${fmtCount(job.progressTotal)}${
          failed ? ` · ${fmtCount(failed)} failed` : ''
        }`
      : undefined;

  switch (job.status) {
    case 'pending':
      return { ...base, status: 'Queued', tone: 'neutral', phase: 'running', progress };
    case 'running':
      return { ...base, status: 'Running', tone: 'run', phase: 'running', progress };
    case 'needs_review':
      return {
        ...base,
        status: 'Needs review',
        tone: 'warn',
        phase: 'waiting',
        detail: counts,
        steps: [{ kind: 'open', label: 'Review' }],
      };
    case 'done':
      return failed
        ? { ...base, status: 'Done with errors', tone: 'warn', phase: 'ended', detail: counts }
        : { ...base, status: 'Done', tone: 'ok', phase: 'ended', detail: counts };
    case 'failed':
      return { ...base, status: 'Failed', tone: 'bad', phase: 'ended', detail: counts };
    case 'aborted':
      return { ...base, status: 'Stopped', tone: 'neutral', phase: 'ended', detail: counts };
    default:
      return { ...base, status: humanizeKey(String(job.status)), tone: 'neutral', phase: 'ended' };
  }
}

// ── Imports ─────────────────────────────────────────────────────────────

/** Counts after an import: "8 added, 2 updated, 2 with problems". */
export function importOutcome(job: ImportJob): string {
  const parts = [`${fmtCount(job.createdIds?.length ?? 0)} added`];
  if (job.updatedIds?.length) parts.push(`${fmtCount(job.updatedIds.length)} updated`);
  if (job.invalidRows) parts.push(`${fmtCount(job.invalidRows)} with problems`);
  return parts.join(', ');
}

export function importItem(job: ImportJob): FxJobItem {
  const base = {
    key: `import:${job.id}`,
    id: job.id,
    kind: 'import' as const,
    title: `Import · ${humanizeKey(job.entityType)}`,
    href: `/imports/${job.id}`,
    sortAt: job.createdAt,
    at: job.createdAt,
    steps: [] as FxJobStep[],
  };
  const rows = job.totalRows > 0 ? plural(job.totalRows, 'row') : undefined;

  switch (job.status) {
    case 'pending':
      return {
        ...base,
        status: 'Not imported yet',
        tone: 'neutral',
        phase: 'waiting',
        detail: rows,
        steps: [{ kind: 'open', label: 'Continue' }],
      };
    case 'validating':
      return { ...base, status: 'Checking', tone: 'run', phase: 'running', detail: rows };
    case 'validated':
      return {
        ...base,
        status: 'Checked',
        tone: 'neutral',
        phase: 'waiting',
        detail: `${fmtCount(job.validRows)} of ${fmtCount(job.totalRows)} rows ready`,
        steps: [{ kind: 'open', label: 'Continue' }],
      };
    case 'importing':
      return { ...base, status: 'Running', tone: 'run', phase: 'running', detail: rows };
    case 'done':
      return job.invalidRows
        ? {
            ...base,
            status: 'Done with errors',
            tone: 'warn',
            phase: 'ended',
            detail: importOutcome(job),
            steps: [{ kind: 'open', label: 'View errors' }],
          }
        : { ...base, status: 'Done', tone: 'ok', phase: 'ended', detail: importOutcome(job) };
    case 'failed':
      return {
        ...base,
        status: 'Failed',
        tone: 'bad',
        phase: 'ended',
        detail: rows,
        steps: job.invalidRows ? [{ kind: 'open', label: 'View errors' }] : [],
      };
    default:
      return { ...base, status: humanizeKey(String(job.status)), tone: 'neutral', phase: 'ended' };
  }
}

// ── Uploads (this browser session) ──────────────────────────────────────

export function uploadItem(item: UploadFileItem, order: number, size: string): FxJobItem {
  const base = {
    key: `upload:${item.id}`,
    id: item.id,
    kind: 'upload' as const,
    title: `Upload · ${item.name}`,
    detail: size,
    // Uploads carry no time; they belong to this session, so they sit on top
    // in the order they were added.
    sortAt: `~${String(1e6 - order).padStart(7, '0')}`,
    steps: [] as FxJobStep[],
  };
  switch (item.status) {
    case 'queued':
      return { ...base, status: 'Queued', tone: 'neutral', phase: 'running' };
    case 'uploading':
      return {
        ...base,
        status: 'Running',
        tone: 'run',
        phase: 'running',
        progress: { done: item.progress, total: 100, pct: pct(item.progress, 100), text: `${Math.round(item.progress)}%` },
      };
    case 'done':
      return { ...base, status: 'Done', tone: 'ok', phase: 'ended' };
    case 'failed':
      return {
        ...base,
        status: 'Failed',
        tone: 'bad',
        phase: 'ended',
        error: item.error,
        steps: [{ kind: 'retry-upload', label: 'Try again' }],
      };
    case 'conflict':
      return {
        ...base,
        status: 'Name taken',
        tone: 'warn',
        phase: 'waiting',
        error: item.conflict?.fileName
          ? `A file named “${item.conflict.fileName}” already exists here.`
          : undefined,
        steps: [
          { kind: 'resolve-upload', label: 'Keep both', mode: 'keep_both' },
          { kind: 'resolve-upload', label: 'Replace', mode: 'replace' },
        ],
      };
    default:
      return { ...base, status: humanizeKey(String(item.status)), tone: 'neutral', phase: 'ended' };
  }
}

// ── ZIP downloads ───────────────────────────────────────────────────────

export function downloadItem(job: DownloadJob): FxJobItem {
  const base = {
    key: `download:${job.id}`,
    id: job.id,
    kind: 'download' as const,
    title: `Download · ${job.filename}`,
    detail: plural(job.fileCount, 'file'),
    sortAt: job.createdAt,
    at: job.createdAt,
    steps: [] as FxJobStep[],
  };
  switch (job.status) {
    case 'pending':
      return { ...base, status: 'Queued', tone: 'neutral', phase: 'running' };
    case 'processing':
      return { ...base, status: 'Running', tone: 'run', phase: 'running' };
    case 'ready':
      return {
        ...base,
        status: 'Ready',
        tone: 'ok',
        phase: 'ended',
        steps: [{ kind: 'download', label: 'Download' }],
      };
    case 'failed':
      return { ...base, status: 'Failed', tone: 'bad', phase: 'ended', error: job.error ?? undefined };
    default:
      return { ...base, status: humanizeKey(String(job.status)), tone: 'neutral', phase: 'ended' };
  }
}

/** Every kind as one list: this session's uploads on top, then newest first. */
export function toJobItems(input: {
  uploads: UploadFileItem[];
  imports: ImportJob[];
  jobs: Job[];
  downloads: DownloadJob[];
  sizeOf: (bytes: number) => string;
}): FxJobItem[] {
  const items = [
    ...input.uploads.map((u, i) => uploadItem(u, i, input.sizeOf(u.sizeBytes))),
    ...input.imports.map(importItem),
    ...input.jobs.map(jobItem),
    ...input.downloads.map(downloadItem),
  ];
  // '~' sorts after every digit, so uploads come first in a descending sort.
  return items.sort((a, b) => (a.sortAt < b.sortAt ? 1 : a.sortAt > b.sortAt ? -1 : 0));
}

/** The end-of-job toast's words, or null for a job that should not toast. */
export function endToast(
  item: FxJobItem,
): { what: string; forWhom?: string; howMany?: string } | null {
  // Uploads finish one file at a time while the user watches the drive; a toast
  // per file would bury the page, so they only show in the list.
  if (item.kind === 'upload') return null;
  if (item.kind === 'import') {
    const forWhom = item.title.replace(/^Import · /, '');
    if (item.tone === 'bad') return { what: 'Import failed', forWhom, howMany: item.detail };
    return { what: 'Import finished', forWhom, howMany: item.detail };
  }
  if (item.kind === 'download') {
    const file = item.title.replace(/^Download · /, '');
    if (item.tone === 'bad') return { what: `${file} could not be prepared` };
    return { what: `${file} is ready`, howMany: item.detail };
  }
  if (item.tone === 'bad') return { what: `${item.title} failed`, howMany: item.detail };
  if (item.status === 'Stopped') return { what: `${item.title} stopped`, howMany: item.detail };
  if (item.phase === 'waiting') return { what: `${item.title} needs review`, howMany: item.detail };
  return { what: `${item.title} finished`, howMany: item.detail };
}
