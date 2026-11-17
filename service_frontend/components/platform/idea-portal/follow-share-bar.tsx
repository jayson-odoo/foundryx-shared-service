'use client';

import { Bell, BellRing, Link2 } from 'lucide-react';
import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { ShareLinkDialog } from './share-link-dialog';

export interface FollowShareBarProps {
  following: boolean;
  followerCount: number;
  /** Null hides Follow (staff / CRM viewers follow from the operator page). */
  onFollow: (() => void) | null;
  /** Null hides Share (the share view itself, test items). */
  onShare: (() => Promise<string>) | null;
  busy?: boolean;
}

/** Lane FEEDBACK-SUBSCRIBE: Follow / Following + follower count and Share
 * (opens the item's read-only link), beside the upvote box. */
export function FollowShareBar({ following, followerCount, onFollow, onShare, busy }: FollowShareBarProps) {
  const [sharing, setSharing] = useState(false);
  return (
    <div className="flex flex-wrap items-center gap-2" data-testid="portal-follow-share">
      {onFollow && (
        <Button
          size="sm"
          variant="outline"
          aria-pressed={following}
          disabled={busy}
          onClick={onFollow}
          className={following ? 'border-primary text-primary' : undefined}
        >
          {following ? <BellRing className="size-4" aria-hidden /> : <Bell className="size-4" aria-hidden />}
          {following ? 'Following' : 'Follow'}
        </Button>
      )}
      <span className="text-sm text-muted-foreground" data-testid="portal-follower-count">
        {followerCount} {followerCount === 1 ? 'follower' : 'followers'}
      </span>
      {onShare && (
        <Button size="sm" variant="ghost" onClick={() => setSharing(true)}>
          <Link2 className="size-4" aria-hidden />
          Share
        </Button>
      )}
      {onShare && <ShareLinkDialog open={sharing} onClose={() => setSharing(false)} loadUrl={onShare} />}
    </div>
  );
}
