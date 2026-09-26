/**
 * Issue #90 W1 (AC-90-102/103/111) - the tenant's status set, in order, with
 * the idea's CURRENT step highlighted (primary ring + font-semibold + a light
 * chip background) so it visually echoes `IdeaHero`'s status pill. `done`
 * steps carry a check; `upcoming` steps are muted. Stays a VERTICAL list at
 * every width (a tenant's status set can run 5+ entries deep - a horizontal
 * rail would crowd). `data-testid="idea-status-timeline"` scopes tests to
 * this region - a step's label can equal `IdeaHero`'s pill text (the current
 * step always does; an off-ramp's `done` step sometimes coincidentally does
 * too), so a query for a bare status word must be scoped to ONE region.
 */
import { Check } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { colorToHex } from '@/components/platform/status-badge';
import { cn } from '@/lib/utils';
import type { PublicIdeaTimelineStep } from '@/types/ideation';

export interface IdeaStatusTimelineProps {
  timeline: PublicIdeaTimelineStep[];
}

export function IdeaStatusTimeline({ timeline }: IdeaStatusTimelineProps) {
  return (
    <Card data-testid="idea-status-timeline">
      <CardContent className="py-4">
        <ol className="flex flex-col gap-1">
          {timeline.map((step) => (
            <li
              key={step.label}
              data-state={step.state}
              className={cn(
                'flex items-center gap-2 rounded-md px-2 py-1.5',
                step.state === 'current' && 'bg-primary/10 ring-1 ring-primary/30',
              )}
            >
              <span
                className="size-2 shrink-0 rounded-full"
                style={{ backgroundColor: colorToHex(step.color) }}
                aria-hidden
              />
              <span
                className={cn(
                  'text-sm',
                  step.state === 'current' && 'font-semibold text-foreground',
                  step.state === 'upcoming' && 'text-muted-foreground',
                )}
              >
                {step.label}
              </span>
              {step.state === 'done' && (
                <Check className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
              )}
            </li>
          ))}
        </ol>
      </CardContent>
    </Card>
  );
}
