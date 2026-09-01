'use client';

import { useCallback } from 'react';
import { toast } from 'sonner';
import { Card, CardContent } from '@/components/ui/card';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { Button } from '@/components/ui/button';
import { ResourceList } from '@/components/platform/resource-list';
import { useMyMeetings } from '@/hooks/use-my-meetings';
import { useDatetime } from '@/hooks/use-datetime';
import type { MeetingsEvent } from '@/types/meetings';
import { useUpcomingEventsListConfig } from './use-upcoming-events-list-config';

/**
 * My meetings (S0 plan §4, AC-S0-6..9).
 *
 * One master toggle and, once it is on, the caller's upcoming events with a
 * capture switch per row. With the toggle off there is nothing to list - the
 * toggle itself is the next-step CTA (AC-S0-9), which is why the empty state
 * carries a control and no explanation.
 */
export function MyMeetingsView() {
  const { optIn, events, loading, saving, error, setEnabled, setEventOptOut } =
    useMyMeetings();
  const { timeZone } = useDatetime();

  const enabled = optIn?.enabled ?? false;

  const toggleMaster = useCallback(
    async (next: boolean) => {
      try {
        await setEnabled(next);
      } catch (e) {
        toast.error(e instanceof Error ? e.message : 'Could not save the change.');
      }
    },
    [setEnabled],
  );

  const toggleCapture = useCallback(
    (event: MeetingsEvent, capture: boolean) => {
      void setEventOptOut(event.id, !capture).catch((e) => {
        toast.error(e instanceof Error ? e.message : 'Could not save the change.');
      });
    },
    [setEventOptOut],
  );

  const config = useUpcomingEventsListConfig(events, {
    timeZone,
    saving,
    onToggleCapture: toggleCapture,
  });

  return (
    <div className="flex flex-col gap-5">
      <Card>
        <CardContent className="flex flex-wrap items-center justify-between gap-4 py-5">
          <Label htmlFor="meetings-master-toggle" className="text-sm font-medium">
            Record my meetings
          </Label>
          <Switch
            id="meetings-master-toggle"
            aria-label="Record my meetings"
            checked={enabled}
            disabled={loading || saving}
            onCheckedChange={(next) => void toggleMaster(next)}
          />
        </CardContent>
      </Card>

      {error && (
        <Card>
          <CardContent className="py-5 text-sm text-destructive">{error}</CardContent>
        </Card>
      )}

      {enabled ? (
        <ResourceList config={config} />
      ) : (
        <Card>
          <CardContent className="flex flex-col items-center gap-4 py-14">
            <p className="text-sm text-muted-foreground">No meetings.</p>
            <Button
              disabled={loading || saving}
              onClick={() => void toggleMaster(true)}
            >
              Record my meetings
            </Button>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
