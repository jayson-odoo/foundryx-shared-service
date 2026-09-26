/**
 * Issue #90 W1 (AC-90-110) - the idea's identity block: number, title, then a
 * meta row (submitter first name, submitted date, votes). The status itself
 * is conveyed by `IdeaStatusTimeline`'s pill-styled CURRENT entry (the plan's
 * "a status pill with a timeline" - one united element, never a duplicate:
 * `view.status` always equals exactly one timeline entry's label, so a
 * SEPARATE bare-text pill here would render the same word twice).
 */
import { ChevronUp } from 'lucide-react';
import { formatDate } from '@/lib/datetime';

export interface IdeaHeroProps {
  ideaNumber: string | null;
  title: string | null;
  submitterFirstName: string | null;
  submittedAt: string | null;
  upvotes: number;
}

export function IdeaHero({
  ideaNumber,
  title,
  submitterFirstName,
  submittedAt,
  upvotes,
}: IdeaHeroProps) {
  return (
    <div className="flex flex-col gap-2">
      <p className="text-sm font-medium text-muted-foreground">{ideaNumber}</p>
      <h1 className="font-heading text-xl font-semibold sm:text-2xl">
        {title ?? `Idea ${ideaNumber}`}
      </h1>
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-muted-foreground">
        {submitterFirstName && <span>Submitted by {submitterFirstName}</span>}
        {submitterFirstName && submittedAt && <span aria-hidden>·</span>}
        {submittedAt && <span>{formatDate(submittedAt)}</span>}
        <span aria-hidden>·</span>
        <span className="inline-flex items-center gap-1">
          <ChevronUp className="size-3.5" />
          {upvotes} {upvotes === 1 ? 'vote' : 'votes'}
        </span>
      </div>
    </div>
  );
}
