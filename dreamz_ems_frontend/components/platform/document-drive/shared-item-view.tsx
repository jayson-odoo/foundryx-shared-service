'use client';

/**
 * One opened "Shared with me" item, browsed IN PLACE inside the Drive page
 * (plan sprint-3/05 follow-up — replaces the standalone scoped page). Resolves
 * the share by token as the signed-in member and renders the shared mini-Drive
 * (preview/download for a file, navigation for a folder) in the Drive's right
 * pane.
 */
import { AlertCircle, Loader2, Lock } from 'lucide-react';
import { ShareBrowser } from './share-browser';
import { usePublicShare } from '@/hooks/use-public-share';

export function SharedItemView({ token }: { token: string }) {
  const share = usePublicShare(token, { preferAuthed: true });

  if (share.loading && !share.view) {
    return (
      <div className="flex items-center justify-center py-20 text-muted-foreground">
        <Loader2 className="size-6 animate-spin" />
      </div>
    );
  }
  if (share.forbidden) {
    return (
      <div className="flex flex-col items-center gap-2 py-20 text-center" data-testid="share-forbidden">
        <Lock className="size-8 text-muted-foreground" />
        <p className="text-sm font-medium">You don’t have access to this item.</p>
      </div>
    );
  }
  if (share.notFound || !share.view) {
    return (
      <div className="flex flex-col items-center gap-2 py-20 text-center" data-testid="share-notfound">
        <AlertCircle className="size-8 text-muted-foreground" />
        <p className="text-sm font-medium">This item isn’t available.</p>
      </div>
    );
  }
  return (
    <div className="p-3">
      <ShareBrowser share={share} />
    </div>
  );
}
