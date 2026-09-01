'use client';

/**
 * Two-pane scoped share layout (plan sprint-3/05 follow-up) - the SAME look as
 * the All-documents Drive (left context rail + bordered right grid), reused by
 * both the in-app scoped view and the anonymous public page so a share opens
 * consistently with the rest of the product. The right pane is the shared
 * mini-Drive (`ShareBrowser`); the left rail names the shared root + who shared it.
 */
import { File as FileIcon, Folder } from 'lucide-react';
import { ShareBrowser } from './share-browser';
import type { UsePublicShare } from '@/hooks/use-public-share';

export function ShareScopedView({
  share,
  contextLabel,
}: {
  share: UsePublicShare;
  contextLabel: string;
}) {
  const v = share.view;
  if (!v) return null;
  const Icon = v.kind === 'folder' ? Folder : FileIcon;

  return (
    <div className="flex flex-col gap-4 lg:flex-row">
      {/* Left context rail */}
      <aside className="shrink-0 lg:w-64">
        <div className="rounded-lg border bg-card p-3 lg:sticky lg:top-4">
          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            {contextLabel}
          </p>
          <div className="mt-2 flex items-center gap-2">
            <Icon className="size-5 shrink-0 text-primary" />
            <span className="min-w-0 truncate text-sm font-medium">{v.title}</span>
          </div>
          {v.tenantName && (
            <p className="mt-1 truncate text-xs text-muted-foreground">Shared by {v.tenantName}</p>
          )}
        </div>
      </aside>

      {/* Right pane - the shared mini-Drive */}
      <div className="min-h-[24rem] min-w-0 flex-1 rounded-lg border bg-background p-3">
        <ShareBrowser share={share} />
      </div>
    </div>
  );
}
