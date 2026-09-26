/**
 * Issue #90 W1 (AC-90-110) - the idea's identity block: number, title, a
 * status pill (SAME `StatusBadge` pill the Ideas app uses, current status
 * label + `statusColor`), then a meta row (submitter first name, submitted
 * date, votes). `data-testid="idea-hero"` scopes tests to this region - the
 * pill's text always equals exactly one entry in `IdeaStatusTimeline` (the
 * current one), so a query for the bare status word must be scoped to ONE of
 * the two regions rather than relying on global uniqueness.
 */
import { ChevronUp } from 'lucide-react';
import {
  StatusBadge,
  colorToTone,
  colorToHex,
  type StatusRegistry,
} from '@/components/platform/status-badge';
import { formatDate } from '@/lib/datetime';

export interface IdeaHeroProps {
  ideaNumber: string | null;
  title: string | null;
  status: string;
  statusColor: string;
  submitterFirstName: string | null;
  submittedAt: string | null;
  upvotes: number;
}

export function IdeaHero({
  ideaNumber,
  title,
  status,
  statusColor,
  submitterFirstName,
  submittedAt,
  upvotes,
}: IdeaHeroProps) {
  const registry: StatusRegistry<string> = {
    [status]: {
      label: status,
      tone: colorToTone(statusColor),
      hex: colorToHex(statusColor),
    },
  };

  return (
    <div className="flex flex-col gap-2" data-testid="idea-hero">
      <p className="text-sm font-medium text-muted-foreground">{ideaNumber}</p>
      <h1 className="font-heading text-xl font-semibold sm:text-2xl">
        {title ?? `Idea ${ideaNumber}`}
      </h1>
      <div>
        <StatusBadge status={status} registry={registry} />
      </div>
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
