'use client';

/**
 * Looping animated guide (plan 64 D12, AC-64-14): frames are data (schematic
 * screen + caption), one guide per platform step. Play/pause, step dots,
 * caption per frame. A platform UI change = edit the frame list.
 */
import { useEffect, useState } from 'react';
import { Pause, Play } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

export interface GuideFrame {
  caption: string;
  /** Schematic screen: the labelled items of the platform page, the target
   *  highlighted. */
  items: string[];
  target: number;
}

export interface GuidePlayerProps {
  frames: GuideFrame[];
  intervalMs?: number;
}

export function GuidePlayer({ frames, intervalMs = 2500 }: GuidePlayerProps) {
  const [index, setIndex] = useState(0);
  const [playing, setPlaying] = useState(true);

  useEffect(() => {
    if (!playing || frames.length < 2) return;
    const timer = window.setInterval(() => setIndex((i) => (i + 1) % frames.length), intervalMs);
    return () => window.clearInterval(timer);
  }, [frames.length, intervalMs, playing]);

  const frame = frames[index];
  if (!frame) return null;

  return (
    <div className="rounded-lg border border-border bg-muted/40 p-3" aria-live="polite">
      <div className="rounded-md border border-border bg-background p-3">
        <ul className="flex flex-col gap-1.5">
          {frame.items.map((item, i) => (
            <li
              key={item}
              className={cn(
                'rounded px-2 py-1.5 text-sm transition-colors',
                i === frame.target
                  ? 'animate-pulse bg-primary/15 font-medium text-foreground ring-1 ring-primary'
                  : 'text-muted-foreground',
              )}
            >
              {item}
            </li>
          ))}
        </ul>
      </div>
      <p className="mt-3 text-sm text-foreground">{frame.caption}</p>
      <div className="mt-2 flex items-center gap-2">
        <Button
          type="button"
          variant="ghost"
          mode="icon"
          size="sm"
          aria-label={playing ? 'Pause guide' : 'Play guide'}
          onClick={() => setPlaying((p) => !p)}
        >
          {playing ? <Pause /> : <Play />}
        </Button>
        <div className="flex items-center gap-1.5">
          {frames.map((f, i) => (
            <button
              key={f.caption}
              type="button"
              aria-label={`Guide step ${i + 1}`}
              aria-current={i === index}
              onClick={() => {
                setIndex(i);
                setPlaying(false);
              }}
              className={cn('size-2 rounded-full', i === index ? 'bg-primary' : 'bg-muted-foreground/40')}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

/** E3 Leads Access (owner-approved mock). */
export const LEADS_ACCESS_GUIDE: GuideFrame[] = [
  { caption: 'Open Meta Business settings', items: ['Business settings', 'Users', 'Accounts', 'Integrations'], target: 0 },
  { caption: 'Integrations, then Leads Access', items: ['Integrations', 'Connected apps', 'Leads Access'], target: 2 },
  { caption: 'Pick the Page, open CRMs', items: ['Pages', 'People', 'CRMs'], target: 2 },
  { caption: 'Assign the app that asked for leads', items: ['Search apps', 'Assign CRM'], target: 1 },
];

/** No Instant Form on the Page yet. */
export const CREATE_FORM_GUIDE: GuideFrame[] = [
  { caption: 'Open the Page in Meta Business Suite', items: ['Home', 'Content', 'All tools'], target: 2 },
  { caption: 'Open Instant Forms', items: ['Ads', 'Instant Forms', 'Insights'], target: 1 },
  { caption: 'Create a form and publish it', items: ['Create form', 'Drafts', 'Published'], target: 0 },
];
