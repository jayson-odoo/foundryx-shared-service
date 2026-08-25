import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { JobsDrawer } from './jobs-drawer';
import type { Job, JobStatus } from '@/types/jobs';

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock('@/hooks/use-datetime', () => ({
  useDatetime: () => ({ formatDateTime: () => 'Jul 11, 2026' }),
}));

function job(status: JobStatus, over: Partial<Job> = {}): Job {
  return {
    id: `job-${status}`,
    tenantId: 't',
    type: 'storage_migration',
    status,
    actorUserId: null,
    payload: null,
    result: null,
    progressTotal: 20,
    progressDone: 8,
    progressFailed: 0,
    error: null,
    createdAt: '2026-07-11T00:00:00Z',
    startedAt: null,
    finishedAt: null,
    ...over,
  };
}

describe('JobsDrawer (generic, type-aware) - AC-10-19', () => {
  it('renders the empty state', () => {
    render(<JobsDrawer open onOpenChange={() => {}} jobs={[]} />);
    expect(screen.getByText('No background jobs yet.')).toBeInTheDocument();
  });

  it('renders a running job with a progress bar + count', () => {
    render(<JobsDrawer open onOpenChange={() => {}} jobs={[job('running')]} />);
    expect(screen.getByText('Storage migration')).toBeInTheDocument();
    expect(screen.getByText('Running')).toBeInTheDocument();
    expect(screen.getByText(/8\/20 copied/)).toBeInTheDocument();
  });

  it('surfaces failures on a needs_review job', () => {
    render(
      <JobsDrawer
        open
        onOpenChange={() => {}}
        jobs={[job('needs_review', { progressFailed: 3, progressDone: 17 })]}
      />,
    );
    expect(screen.getByText('Needs review')).toBeInTheDocument();
    expect(screen.getByText(/3 failed/)).toBeInTheDocument();
  });

  it('renders done + failed + aborted states', () => {
    render(
      <JobsDrawer
        open
        onOpenChange={() => {}}
        jobs={[
          job('done', { id: 'a', progressDone: 20 }),
          job('failed', { id: 'b', error: 'boom' }),
          job('aborted', { id: 'c' }),
        ]}
      />,
    );
    expect(screen.getByText('Done')).toBeInTheDocument();
    expect(screen.getByText('Failed')).toBeInTheDocument();
    expect(screen.getByText('Aborted')).toBeInTheDocument();
  });
});
