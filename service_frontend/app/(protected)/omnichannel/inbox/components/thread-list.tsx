'use client';

/**
 * Inbox left panel (plan 05 §6): assignee buckets (All | Mine | Unassigned),
 * status/priority filters, search, and the thread rows - live-sorted by
 * recency via useConversations.
 */
import { Search } from 'lucide-react';

import { StatusBadge } from '@/components/platform/status-badge';
import {
  THREAD_PRIORITY_REGISTRY,
  THREAD_STATUS_REGISTRY,
} from '@/components/platform/conversation-drawer';
import { Avatar, AvatarFallback } from '@/components/ui/avatar';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { ScrollArea } from '@/components/ui/scroll-area';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import type { ConversationFilters } from '@/hooks/use-conversations';
import { cn } from '@/lib/utils';
import type { ConversationThread, ThreadPriority, ThreadStatus } from '@/types/omnichannel';

export interface ThreadListProps {
  threads: ConversationThread[];
  isLoading: boolean;
  error: string | null;
  filters: ConversationFilters;
  setFilters: (patch: Partial<ConversationFilters>) => void;
  selectedId: string | null;
  onSelect: (contactId: string) => void;
}

function initials(name: string): string {
  return name
    .split(/\s+/)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase() ?? '')
    .join('');
}

function relativeTime(iso: string | null): string {
  if (!iso) return '';
  const diff = Date.now() - Date.parse(iso);
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return 'now';
  if (mins < 60) return `${mins}m`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h`;
  return `${Math.floor(hours / 24)}d`;
}

export function ThreadList({
  threads,
  isLoading,
  error,
  filters,
  setFilters,
  selectedId,
  onSelect,
}: ThreadListProps) {
  return (
    <div className="flex h-full flex-col" data-testid="thread-list">
      <div className="space-y-2.5 border-b p-3">
        <div className="relative">
          <Search className="absolute start-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            className="ps-8"
            placeholder="Search conversations…"
            value={filters.search}
            onChange={(e) => setFilters({ search: e.target.value })}
            data-testid="thread-search"
          />
        </div>
        <Tabs
          value={filters.assignee}
          onValueChange={(v) => setFilters({ assignee: v as ConversationFilters['assignee'] })}
        >
          {/* Segmented filter switch, not content navigation (AC-DLA-12) -
              pinned explicitly, the tab strip default is now `line`. */}
          <TabsList className="w-full" variant="default">
            <TabsTrigger value="all" className="flex-1" data-testid="bucket-all">
              All
            </TabsTrigger>
            <TabsTrigger value="me" className="flex-1" data-testid="bucket-me">
              Mine
            </TabsTrigger>
            <TabsTrigger value="unassigned" className="flex-1" data-testid="bucket-unassigned">
              Unassigned
            </TabsTrigger>
          </TabsList>
        </Tabs>
        <div className="flex gap-2">
          <Select
            value={filters.status}
            onValueChange={(v) => setFilters({ status: v as ThreadStatus | 'ALL' })}
          >
            <SelectTrigger size="sm" className="flex-1" aria-label="Status filter" data-testid="filter-status">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="ALL">All statuses</SelectItem>
              <SelectItem value="OPEN">Open</SelectItem>
              <SelectItem value="SNOOZED">Snoozed</SelectItem>
              <SelectItem value="CLOSED">Closed</SelectItem>
            </SelectContent>
          </Select>
          <Select
            value={filters.priority}
            onValueChange={(v) => setFilters({ priority: v as ThreadPriority | 'ALL' })}
          >
            <SelectTrigger size="sm" className="flex-1" aria-label="Priority filter" data-testid="filter-priority">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="ALL">All priorities</SelectItem>
              <SelectItem value="URGENT">Urgent</SelectItem>
              <SelectItem value="HIGH">High</SelectItem>
              <SelectItem value="MEDIUM">Medium</SelectItem>
              <SelectItem value="LOW">Low</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      <ScrollArea className="min-h-0 flex-1">
        {isLoading && threads.length === 0 ? (
          <div className="space-y-2 p-3">
            <Skeleton className="h-16 w-full" />
            <Skeleton className="h-16 w-full" />
            <Skeleton className="h-16 w-full" />
          </div>
        ) : error ? (
          <p className="p-4 text-sm text-destructive">{error}</p>
        ) : threads.length === 0 ? (
          <p className="p-6 text-center text-sm text-muted-foreground" data-testid="thread-list-empty">
            No conversations here.
          </p>
        ) : (
          <ul>
            {threads.map((t) => (
              <li key={t.id}>
                <button
                  type="button"
                  onClick={() => onSelect(t.id)}
                  className={cn(
                    'flex w-full items-start gap-3 border-b px-3 py-2.5 text-start transition-colors hover:bg-accent',
                    selectedId === t.id && 'bg-accent',
                  )}
                  data-testid={`thread-row-${t.id}`}
                >
                  <Avatar className="mt-0.5 size-9 shrink-0">
                    <AvatarFallback>{initials(t.name)}</AvatarFallback>
                  </Avatar>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center justify-between gap-2">
                      <span className={cn('truncate text-sm', t.unreadCount > 0 ? 'font-semibold' : 'font-medium')}>
                        {t.name}
                      </span>
                      <span className="shrink-0 text-2xs text-muted-foreground">
                        {relativeTime(t.lastMessageAt)}
                      </span>
                    </div>
                    <div className="flex items-center justify-between gap-2">
                      <span className="truncate text-xs text-muted-foreground">{t.lastMessagePreview}</span>
                      {t.unreadCount > 0 && (
                        <Badge variant="primary" size="sm" shape="circle" data-testid="unread-badge">
                          {t.unreadCount}
                        </Badge>
                      )}
                    </div>
                    <div className="mt-1 flex items-center gap-1.5">
                      <StatusBadge status={t.status} registry={THREAD_STATUS_REGISTRY} size="sm" />
                      <StatusBadge status={t.priority} registry={THREAD_PRIORITY_REGISTRY} size="sm" />
                      <span className="ms-auto truncate text-2xs text-muted-foreground">
                        {t.assignedUserName ?? 'Unassigned'}
                      </span>
                    </div>
                  </div>
                </button>
              </li>
            ))}
          </ul>
        )}
      </ScrollArea>
    </div>
  );
}
