'use client';

/**
 * Logs tab (plan sprint-2/08 D16) — n8n-style two-pane: a run list on the LEFT,
 * the selected run's replay canvas + data on the RIGHT. "Debug in editor"
 * (inside the replay) hands the run off to the Editor tab.
 */
import { useCallback, useEffect, useState } from 'react';
import { FlaskConical } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { useDatetime } from '@/hooks/use-datetime';
import { cn } from '@/lib/utils';
import { workflowService } from '@/services/workflow-service';
import type { WorkflowRunDetail, WorkflowRunListItem } from '@/types/workflows';
import { RunReplay } from './run-replay';
import { RunStatusBadge } from './run-status-badge';

const PAGE_SIZE = 25;
const SEGMENTS = [
  { value: 'all', label: 'All runs' },
  { value: 'success', label: 'Success' },
  { value: 'failed', label: 'Failed' },
  { value: 'running', label: 'Running' },
  { value: 'pending', label: 'Pending' },
  { value: 'cancelled', label: 'Cancelled' },
];

function formatDuration(ms: number | null): string {
  if (ms == null) return '—';
  return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`;
}

export interface WorkflowRunsProps {
  workflowId: string;
  onDebugInEditor: (runId: string) => void;
  /** Bump to force a reload (e.g. after a manual run). */
  reloadToken?: number;
}

export function WorkflowRuns({ workflowId, onDebugInEditor, reloadToken = 0 }: WorkflowRunsProps) {
  const { formatDateTime } = useDatetime();
  const [rows, setRows] = useState<WorkflowRunListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [loading, setLoading] = useState(true);
  const [segment, setSegment] = useState('all');
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [runDetail, setRunDetail] = useState<WorkflowRunDetail | null>(null);

  const openRun = useCallback((runId: string) => {
    setSelectedRunId(runId);
    workflowService.getRun(runId).then((detail) => setRunDetail(detail));
  }, []);

  // First page (and reset on segment / reload). Paginate — never fetch all runs.
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    workflowService
      .listRuns(workflowId, { page: 0, pageSize: PAGE_SIZE, segment })
      .then((result) => {
        if (cancelled) return;
        setRows(result.data);
        setTotal(result.total);
        setPage(0);
        if (result.data.length) openRun(result.data[0].id);
        else {
          setSelectedRunId(null);
          setRunDetail(null);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [workflowId, segment, reloadToken, openRun]);

  const loadMore = useCallback(() => {
    const next = page + 1;
    setLoading(true);
    workflowService
      .listRuns(workflowId, { page: next, pageSize: PAGE_SIZE, segment })
      .then((result) => {
        setRows((prev) => [...prev, ...result.data]);
        setTotal(result.total);
        setPage(next);
      })
      .finally(() => setLoading(false));
  }, [page, workflowId, segment]);

  return (
    <div className="flex items-start gap-4" data-testid="workflow-runs">
      <aside className="w-72 shrink-0">
        <Select value={segment} onValueChange={setSegment}>
          <SelectTrigger className="mb-2 w-full" aria-label="Filter runs by status">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {SEGMENTS.map((s) => (
              <SelectItem key={s.value} value={s.value}>
                {s.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <div className="flex max-h-[calc(100vh-19rem)] min-h-[420px] flex-col gap-1 overflow-auto rounded-lg border border-border p-1">
          {loading && <p className="px-2 py-6 text-center text-xs text-muted-foreground">Loading…</p>}
          {!loading && rows.length === 0 && (
            <p className="px-2 py-6 text-center text-xs text-muted-foreground" data-testid="run-list-empty">
              No runs yet. Run the workflow to see executions here.
            </p>
          )}
          {rows.map((run) => (
            <button
              key={run.id}
              type="button"
              data-testid={`run-row-${run.id}`}
              onClick={() => openRun(run.id)}
              className={cn(
                'flex flex-col gap-1 rounded-md border px-2.5 py-2 text-left transition-colors',
                selectedRunId === run.id
                  ? 'border-primary bg-accent'
                  : 'border-transparent hover:bg-accent/50',
              )}
            >
              <div className="flex items-center justify-between gap-2">
                <RunStatusBadge status={run.status} size="sm" />
                <span className="text-[11px] text-muted-foreground">{formatDuration(run.durationMs)}</span>
              </div>
              <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                <span>{run.startedAt ? formatDateTime(run.startedAt) : '—'}</span>
                {run.isTest && <FlaskConical className="size-3" />}
              </div>
            </button>
          ))}
          {rows.length < total && (
            <Button
              variant="ghost"
              size="sm"
              className="mt-1"
              disabled={loading}
              onClick={loadMore}
              data-testid="runs-load-more"
            >
              {loading ? 'Loading…' : `Load more (${total - rows.length})`}
            </Button>
          )}
        </div>
      </aside>

      <div className="min-w-0 flex-1">
        {runDetail ? (
          <RunReplay run={runDetail} onDebugInEditor={onDebugInEditor} />
        ) : (
          <div className="flex h-[calc(100vh-23rem)] min-h-[420px] items-center justify-center rounded-lg border border-dashed border-border text-sm text-muted-foreground">
            {rows.length ? 'Select a run to view it.' : 'No runs yet.'}
          </div>
        )}
      </div>
    </div>
  );
}
