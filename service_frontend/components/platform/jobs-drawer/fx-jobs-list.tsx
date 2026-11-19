'use client';

/**
 * The one Jobs list (Foundryx UIUX switch only, slice W3-JOBS): uploads,
 * imports, background jobs and ZIP downloads as jobs, newest first. Each row
 * says what it is and for what, its status chip, real progress while it runs
 * ("820 of 1,240") and its next step as a text button; a row with a page opens
 * it. Presentational: the steps call the providers' own functions, so every
 * request is the one the old drawers sent.
 */
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { Archive, Settings2, Upload } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { ClampedText } from '@/components/platform/clamped-text';
import { FxFileIcon } from '@/components/fx/icons';
import { useDatetime } from '@/hooks/use-datetime';
import { FxJobBar, FxJobChip } from './fx-job-chip';
import type { FxJobItem, FxJobKind, FxJobStep } from './fx-job-items';

export interface FxJobsListHandlers {
  /** Called before following a job's page (the sheet closes). */
  onNavigate: () => void;
  onDownload: (id: string) => void;
  onRetryUpload: (id: string) => void;
  onResolveUpload: (id: string, mode: 'replace' | 'keep_both') => void;
  onRemoveUpload: (id: string) => void;
}

function KindIcon({ kind }: { kind: FxJobKind }) {
  const cls = 'mt-0.5 size-4.5 shrink-0 text-(--fx-ink-3)';
  if (kind === 'import') return <FxFileIcon type="CSV" arrow="up" size={18} className={cls} />;
  if (kind === 'upload') return <Upload aria-hidden="true" className={cls} />;
  if (kind === 'download') return <Archive aria-hidden="true" className={cls} />;
  return <Settings2 aria-hidden="true" className={cls} />;
}

export function FxJobsList({
  items,
  handlers,
}: {
  items: FxJobItem[];
  handlers: FxJobsListHandlers;
}) {
  if (items.length === 0) {
    return (
      <div className="flex flex-1 items-center justify-center p-8 text-center text-sm text-(--fx-ink-3)">
        No jobs yet
      </div>
    );
  }
  return (
    <ul aria-label="Jobs" className="flex-1 divide-y divide-(--fx-line) overflow-y-auto">
      {items.map((item) => (
        <FxJobRow key={item.key} item={item} handlers={handlers} />
      ))}
    </ul>
  );
}

function FxJobRow({ item, handlers }: { item: FxJobItem; handlers: FxJobsListHandlers }) {
  const router = useRouter();
  const { formatRelative } = useDatetime();
  const open = item.href
    ? () => {
        handlers.onNavigate();
        router.push(item.href!);
      }
    : undefined;

  const runStep = (step: FxJobStep) => {
    if (step.kind === 'download') handlers.onDownload(item.id);
    else if (step.kind === 'retry-upload') handlers.onRetryUpload(item.id);
    else if (step.kind === 'resolve-upload') handlers.onResolveUpload(item.id, step.mode);
    else open?.();
  };

  const quiet = [item.detail, item.at ? formatRelative(item.at) : undefined]
    .filter(Boolean)
    .join(' · ');

  return (
    // The row click is a pointer shortcut; the title link is the keyboard path.
    // eslint-disable-next-line jsx-a11y/click-events-have-key-events
    <li
      data-fx-job={item.kind}
      className={
        open
          ? 'flex cursor-pointer items-start gap-3 px-4 py-3 transition-colors duration-(--fx-t-hover) ease-(--fx-ease-out) hover:bg-(--fx-surface-2)'
          : 'flex items-start gap-3 px-4 py-3'
      }
      onClick={(event) => {
        if (!open) return;
        // Steps and the title link handle their own clicks.
        if ((event.target as HTMLElement).closest('button, a')) return;
        open();
      }}
    >
      <KindIcon kind={item.kind} />
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <div className="flex min-w-0 items-start justify-between gap-2">
          {item.href ? (
            <Link
              href={item.href}
              onClick={() => handlers.onNavigate()}
              className="min-w-0 text-sm font-semibold text-(--fx-ink) hover:text-(--fx-link) focus-visible:text-(--fx-link)"
            >
              <ClampedText text={item.title} lines={1} />
            </Link>
          ) : (
            <span className="min-w-0 text-sm font-semibold text-(--fx-ink)">
              <ClampedText text={item.title} lines={1} />
            </span>
          )}
          <FxJobChip label={item.status} tone={item.tone} />
        </div>
        {item.progress && (
          <div className="flex items-center gap-2">
            <FxJobBar pct={item.progress.pct} label={`${item.title}: ${item.progress.text}`} />
            <span className="shrink-0 text-xs text-(--fx-ink-2) tabular-nums">{item.progress.text}</span>
          </div>
        )}
        {quiet && <p className="text-xs text-(--fx-ink-3) tabular-nums">{quiet}</p>}
        {item.error && <ClampedText text={item.error} lines={1} className="text-xs text-destructive" />}
        {(item.steps.length > 0 || (item.kind === 'upload' && item.status === 'Failed')) && (
          <div className="-ms-2 flex flex-wrap items-center gap-1">
            {item.steps.map((step) => (
              <Button
                key={step.label}
                type="button"
                variant="fx-text"
                size="sm"
                onClick={() => runStep(step)}
              >
                {step.label}
              </Button>
            ))}
            {item.kind === 'upload' && item.status === 'Failed' && (
              <Button
                type="button"
                variant="fx-text"
                size="sm"
                className="text-(--fx-ink-2)"
                onClick={() => handlers.onRemoveUpload(item.id)}
              >
                Dismiss
              </Button>
            )}
          </div>
        )}
      </div>
    </li>
  );
}
