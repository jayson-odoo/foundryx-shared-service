'use client';

import { useState } from 'react';
import { toast } from '@/lib/toast';
import { useIdeaPortal, usePortalList } from '@/hooks/use-idea-portal';
import { ListSearchInput } from '@/components/platform/list-search-input';
import { MultiSelect } from '@/components/platform/multi-select';
import { SearchSelect } from '@/components/platform/search-select';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { IdeaCard } from './idea-card';
import { SubmitIdeaForm } from './submit-idea-form';
import { PortalLoading, PortalMessage } from './portal-states';

const STATUS_OPTIONS = [
  { value: 'under_review', label: 'Under review' },
  { value: 'planned', label: 'Planned' },
  { value: 'in_progress', label: 'In progress' },
  { value: 'complete', label: 'Complete' },
  { value: 'closed', label: 'Closed' },
];
const SORT_OPTIONS = [
  { value: 'top', label: 'Top' },
  { value: 'new', label: 'Newest' },
];
const PAGE_SIZE = 25;

export function FeedbackView() {
  const { paths } = useIdeaPortal();
  const [q, setQ] = useState('');
  const [columns, setColumns] = useState<string[]>([]);
  const [sort, setSort] = useState<'top' | 'new'>('top');
  const [mine, setMine] = useState(false);
  const [page, setPage] = useState(1);
  const list = usePortalList({
    q: q || undefined,
    columns,
    sort,
    mine,
    includeClosed: columns.includes('closed'),
    page,
    pageSize: PAGE_SIZE,
  });
  const total = list.data?.total ?? 0;
  const lastPage = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const onVote = (id: string) => {
    list.vote(id).catch(() => toast.error('Could not save your vote.'));
  };

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-[20rem_minmax(0,1fr)] lg:items-start">
      <aside className="order-2 lg:order-1">
        <SubmitIdeaForm />
      </aside>
      <section className="order-1 flex min-w-0 flex-col gap-3 lg:order-2">
        <h1 className="font-heading text-xl font-semibold">Feedback</h1>
        <div className="flex flex-wrap items-center gap-2">
          <ListSearchInput
            value={q}
            onChange={(v: string) => {
              setQ(v);
              setPage(1);
            }}
            placeholder="Search ideas"
            className="min-w-0 flex-1"
          />
          <MultiSelect
            className="w-full sm:w-56"
            options={STATUS_OPTIONS}
            value={columns}
            onChange={(v) => {
              setColumns(v);
              setPage(1);
            }}
            placeholder="All statuses"
            size="sm"
          />
          <SearchSelect
            className="w-32"
            ariaLabel="Sort"
            options={SORT_OPTIONS}
            value={sort}
            onChange={(v) => setSort(v === 'new' ? 'new' : 'top')}
          />
          <Button
            variant={mine ? 'primary' : 'outline'}
            size="sm"
            aria-pressed={mine}
            onClick={() => {
              setMine((m) => !m);
              setPage(1);
            }}
          >
            My ideas
          </Button>
        </div>
        {list.loading && !list.data && <PortalLoading />}
        {list.error && <PortalMessage text="Ideas could not be loaded." />}
        {list.data && (
          <Card className="divide-y divide-border overflow-hidden" data-testid="portal-feedback-list">
            {list.data.items.length === 0 ? (
              <p className="p-6 text-center text-sm text-muted-foreground">No ideas</p>
            ) : (
              list.data.items.map((idea) => (
                <IdeaCard key={idea.id} idea={idea} variant="row" href={paths.idea(idea.id)} onVote={onVote} />
              ))
            )}
          </Card>
        )}
        {lastPage > 1 && (
          <div className="flex items-center justify-end gap-2 text-sm">
            <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
              Previous
            </Button>
            <span className="text-muted-foreground">
              {page} / {lastPage}
            </span>
            <Button variant="outline" size="sm" disabled={page >= lastPage} onClick={() => setPage((p) => p + 1)}>
              Next
            </Button>
          </div>
        )}
      </section>
    </div>
  );
}
