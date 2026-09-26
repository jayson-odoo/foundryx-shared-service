/**
 * Issue #90 W1 (AC-90-110) - the idea's identity block: number, title, a
 * status pill (SAME `StatusBadge` pill the Ideas app uses, current status
 * label + `statusColor`), then a meta row (submitter first name, submitted
 * date, votes). `data-testid="idea-hero"` scopes tests to this region - the
 * pill's text always equals exactly one entry in `IdeaStatusTimeline` (the
 * current one), so a query for the bare status word must be scoped to ONE of
 * the two regions rather than relying on global uniqueness.
 *
 * Review fix S5: a null `title` used to fall back to `Idea <number>`, which
 * repeated the number the muted line above it already showed. A null title
 * now falls back to a truncated `problem` (the idea still needs SOME
 * heading) - only when `problem` is ALSO null does the number stand alone,
 * shown exactly once.
 */
import { ChevronUp } from 'lucide-react';
import {
  StatusBadge,
  colorToTone,
  colorToHex,
  type StatusRegistry,
} from '@/components/platform/status-badge';
import { ClampedText } from '@/components/platform/clamped-text';
import { formatDate } from '@/lib/datetime';

export interface IdeaHeroProps {
  ideaNumber: string | null;
  title: string | null;
  problem: string | null;
  status: string;
  statusColor: string;
  submitterFirstName: string | null;
  submittedAt: string | null;
  upvotes: number;
}

const HEADING_CLASS = 'font-heading text-xl font-semibold sm:text-2xl';

export function IdeaHero({
  ideaNumber,
  title,
  problem,
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
      {title ? (
        // `role="heading"` (not a literal `<h1>`) so the `problem` fallback
        // below can reuse the SAME heading slot with `ClampedText`, whose
        // rendered `<p>` would be invalid flow content nested in an `<h1>`.
        <div role="heading" aria-level={1} className={HEADING_CLASS}>
          {title}
        </div>
      ) : (
        problem && (
          <div role="heading" aria-level={1}>
            <ClampedText text={problem} lines={2} className={HEADING_CLASS} />
          </div>
        )
      )}
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
