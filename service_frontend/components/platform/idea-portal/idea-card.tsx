'use client';

import Link from 'next/link';
import { ClampedText } from '@/components/platform/clamped-text';
import type { PortalCard } from '@/types/idea-portal';
import { UpvoteBox } from './upvote-box';
import { PortalStatusPill } from './portal-status-pill';

export interface IdeaCardProps {
  idea: PortalCard;
  href: string;
  onVote: (id: string) => void;
  /** List rows show the status pill + comment count; roadmap cards do not. */
  variant?: 'card' | 'row';
}

export function IdeaCard({ idea, href, onVote, variant = 'card' }: IdeaCardProps) {
  if (variant === 'row') {
    return (
      <Link
        href={href}
        data-testid="portal-idea-row"
        className="flex items-start gap-3 p-4 transition-colors hover:bg-muted/50"
      >
        <UpvoteBox count={idea.upvotes} voted={idea.myVote} onVote={() => onVote(idea.id)} />
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <ClampedText text={idea.title} lines={2} className="font-medium text-foreground" />
          <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            {idea.statusLabel && <PortalStatusPill label={idea.statusLabel} color={idea.statusColor} />}
            {idea.ideaNumber && <span>{idea.ideaNumber}</span>}
            <span>
              {idea.commentCount} {idea.commentCount === 1 ? 'comment' : 'comments'}
            </span>
            {idea.isMine && <span className="text-primary">Your idea</span>}
          </div>
        </div>
      </Link>
    );
  }
  return (
    <Link
      href={href}
      data-testid="portal-idea-card"
      className="flex gap-3 rounded-lg border border-border bg-background p-3 transition-colors hover:border-primary/60"
    >
      <UpvoteBox count={idea.upvotes} voted={idea.myVote} onVote={() => onVote(idea.id)} />
      <div className="flex min-w-0 flex-col gap-0.5">
        <span className="text-xs text-muted-foreground">
          {idea.ideaNumber}
          {idea.isMine && <span className="text-primary"> · Yours</span>}
        </span>
        <ClampedText text={idea.title} lines={3} className="text-sm font-medium text-foreground" />
      </div>
    </Link>
  );
}
