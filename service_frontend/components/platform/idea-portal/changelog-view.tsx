'use client';

import Link from 'next/link';
import { ChevronUp } from 'lucide-react';
import { useDatetime } from '@/hooks/use-datetime';
import { useIdeaPortal, usePortalChangelog } from '@/hooks/use-idea-portal';
import { Card, CardContent } from '@/components/ui/card';
import { parseUtc } from '@/lib/datetime';
import type { PortalChangelogItem } from '@/types/idea-portal';
import { PortalStatusPill } from './portal-status-pill';
import { PortalLoading, PortalMessage } from './portal-states';

function monthKey(iso: string, timeZone: string): string {
  const d = parseUtc(iso);
  if (!d) return '';
  return new Intl.DateTimeFormat('en-GB', { month: 'long', year: 'numeric', timeZone }).format(d);
}

/** Changelog (Q3 a): delivered ideas, grouped by month, newest first. */
export function ChangelogView() {
  const { paths } = useIdeaPortal();
  const { formatDate, timeZone } = useDatetime();
  const log = usePortalChangelog();

  const groups: { month: string; items: PortalChangelogItem[] }[] = [];
  for (const item of log.data?.items ?? []) {
    const month = monthKey(item.deliveredAt, timeZone);
    const last = groups[groups.length - 1];
    if (last && last.month === month) last.items.push(item);
    else groups.push({ month, items: [item] });
  }

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-4">
      <h1 className="font-heading text-xl font-semibold">Changelog</h1>
      {log.loading && !log.data && <PortalLoading />}
      {log.error && <PortalMessage text="The changelog could not be loaded." />}
      {log.data && groups.length === 0 && <p className="text-sm text-muted-foreground">Nothing delivered yet</p>}
      <ol className="flex flex-col gap-6 border-l border-border pl-6" data-testid="portal-changelog">
        {groups.map((g) => (
          <li key={g.month} className="flex flex-col gap-2">
            <p className="text-xs text-muted-foreground">{g.month}</p>
            {g.items.map((item) => (
              <Link key={item.id} href={paths.idea(item.id)}>
                <Card className="transition-colors hover:border-primary/60">
                  <CardContent className="flex flex-col gap-1.5 py-4">
                    <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                      {item.statusLabel && <PortalStatusPill label={item.statusLabel} color={item.statusColor} />}
                      {item.ideaNumber && <span>{item.ideaNumber}</span>}
                      <span>{formatDate(item.deliveredAt)}</span>
                    </div>
                    <h2 className="font-heading font-semibold">{item.title}</h2>
                    {item.note && <p className="text-sm text-muted-foreground">{item.note}</p>}
                    <p className="inline-flex items-center gap-1 text-xs text-muted-foreground">
                      <ChevronUp className="size-3.5" aria-hidden />
                      {item.upvotes} {item.upvotes === 1 ? 'vote' : 'votes'}
                    </p>
                  </CardContent>
                </Card>
              </Link>
            ))}
          </li>
        ))}
      </ol>
    </div>
  );
}
