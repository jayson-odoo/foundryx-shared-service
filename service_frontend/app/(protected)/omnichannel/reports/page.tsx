'use client';

/**
 * Omnichannel Reports (plan 30, roadmap A9, AC-RPT-44) - a report
 * `SearchSelect` over the shared filter bar, backing all seven reports.
 * Workspace resolves exactly like Contacts/Dashboard (D-A9-16); gated
 * `reports.read` (main-session override of D-A9-10).
 */
import { Fragment, useCallback, useEffect, useMemo, useState } from 'react';
import { LoaderCircleIcon } from 'lucide-react';
import { Container } from '@/components/common/container';
import { RequirePermission } from '@/components/common/require-permission';
import { PageHeader } from '@/components/platform/page-header';
import { SearchSelect } from '@/components/platform/search-select';
import { Button } from '@/components/ui/button';
import { useCan } from '@/hooks/use-can';
import { useActiveWorkspace } from '@/hooks/use-contacts';
import { useReportFilters } from '@/hooks/use-report-filters';
import { useReportMeta } from '@/hooks/use-report-meta';
import { useWorkspaceChannels } from '@/hooks/use-workspace-channels';
import { useWorkspaceMembers } from '@/hooks/use-workspace-members';
import type { ReportKey } from '@/types/omnichannel';
import { ReportFilterBar } from '../components/report-filter-bar';
import { AssignmentsReport } from './components/assignments-report';
import { ConversationsReport } from './components/conversations-report';
import { LeaderboardReport } from './components/leaderboard-report';
import { MessagesReport } from './components/messages-report';
import { ReportPicker } from './components/report-picker';
import { ResolutionsReport } from './components/resolutions-report';
import { ResponsesReport } from './components/responses-report';
import { UsersReport } from './components/users-report';
import { useReportExport } from './components/use-report-export';

const DEFAULT_REPORT: ReportKey = 'conversations';

function readReportKeyFromUrl(): ReportKey {
  if (typeof window === 'undefined') return DEFAULT_REPORT;
  const value = new URLSearchParams(window.location.search).get('report');
  const valid: ReportKey[] = ['conversations', 'responses', 'resolutions', 'messages', 'users', 'leaderboard', 'assignments'];
  return valid.includes(value as ReportKey) ? (value as ReportKey) : DEFAULT_REPORT;
}

export default function OmnichannelReportsPage() {
  const { can } = useCan();
  const { workspaceId, workspaces, ready, setWorkspaceId } = useActiveWorkspace();
  const { members } = useWorkspaceMembers(workspaceId);
  const { meta, loading: metaLoading, error: metaError } = useReportMeta(workspaceId);
  const { state, setDateRange, setUserId, setChannelId, setGranularity, setGroupBy, filters } = useReportFilters();
  const [reportKey, setReportKey] = useState<ReportKey>(() => readReportKeyFromUrl());

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const url = new URL(window.location.href);
    url.searchParams.set('report', reportKey);
    window.history.replaceState(null, '', url);
  }, [reportKey]);

  const { options: channelOptions } = useWorkspaceChannels(workspaceId);

  const currentDescriptor = meta?.reports.find((r) => r.key === reportKey);

  // A `groupBy` carried over from the previous report (or a hand-edited URL)
  // would be a server 422 - `supportsGroupBy` is per report. Clear it as soon
  // as the descriptor says the current report can't take it (S-5, review
  // round 1: the value is URL-synced now, so it outlives a report switch).
  useEffect(() => {
    if (!currentDescriptor) return;
    if (state.groupBy && !currentDescriptor.supportsGroupBy.includes(state.groupBy)) setGroupBy(null);
  }, [currentDescriptor, state.groupBy, setGroupBy]);

  // The effective group-by for THIS report, and the one `ReportFilters` both
  // the report request and the Export request are built from - so an export
  // taken while looking at "By agent" carries `groupBy=user` (S-5).
  const groupBy = currentDescriptor?.supportsGroupBy.includes(state.groupBy ?? '') ? state.groupBy : null;
  const scopedFilters = useMemo(
    () => ({ ...filters, groupBy: groupBy ?? undefined }),
    [filters, groupBy],
  );
  const { exporting, runExport } = useReportExport(workspaceId, reportKey, scopedFilters);
  const canExport = can('reports.export');

  const onReportChange = useCallback(
    (next: ReportKey) => {
      setReportKey(next);
      setGroupBy(null);
    },
    [setGroupBy],
  );

  // N-1 (review round 2): `useReportMeta(null)` (pre-`ready`) settles at
  // loading=false / meta=null / error=false, and the commit right after the
  // workspace id lands - BEFORE the fetch effect re-runs - carries that same
  // state. Treating `!meta` as an error there replaced the whole page with
  // "Couldn't load" on every normal load. So: a workspace whose catalog has
  // not arrived yet is a LOADING state; only an actual fetch failure is the
  // error state; and no workspace at all (BL-SS-081 - a role without
  // `workspaces.read`) renders the page with an empty body, as before.
  const metaPending = Boolean(workspaceId) && !meta && !metaError;
  if (!ready || metaLoading || metaPending) {
    return (
      <Container width="fluid">
        <div className="flex items-center justify-center py-24 text-muted-foreground">
          <LoaderCircleIcon className="size-6 animate-spin" />
        </div>
      </Container>
    );
  }

  // The report catalog IS the page (which reports exist, which take a
  // group-by, which export). A hardcoded fallback list would silently drift
  // from the server's and offer reports/controls that may not exist - so a
  // meta failure is an error state, not a guess (nit, review round 1).
  if (metaError) {
    return (
      <RequirePermission permission="reports.read">
        <Container width="fluid">
          <div className="flex items-center justify-center py-24 text-sm text-muted-foreground">
            Couldn&apos;t load the reports.
          </div>
        </Container>
      </RequirePermission>
    );
  }

  return (
    <RequirePermission permission="reports.read">
      <Fragment>
        <Container width="fluid">
          <PageHeader
            description={`Timezone: ${filters.tz}`}
            actions={
              workspaces.length > 1 ? (
                <SearchSelect
                  ariaLabel="Workspace"
                  className="w-56"
                  value={workspaceId}
                  onChange={setWorkspaceId}
                  options={workspaces.map((w) => ({ label: w.name, value: w.id }))}
                />
              ) : undefined
            }
          />
        </Container>

        <Container width="fluid">
          <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center sm:justify-between">
            <ReportPicker value={reportKey} onChange={onReportChange} reports={meta?.reports ?? []} />
            {canExport && (currentDescriptor?.exportable ?? true) && (
              <Button variant="outline" size="sm" disabled={!workspaceId || exporting} onClick={() => void runExport()}>
                {exporting ? 'Exporting...' : 'Export'}
              </Button>
            )}
          </div>
          <ReportFilterBar
            dateRange={state.dateRange}
            onDateRangeChange={setDateRange}
            timeZone={filters.tz}
            userId={state.userId}
            onUserIdChange={setUserId}
            members={members.map((m) => ({ id: m.userId, name: m.name ?? m.email }))}
            channelId={state.channelId}
            onChannelIdChange={setChannelId}
            channels={channelOptions}
            granularity={state.granularity}
            onGranularityChange={setGranularity}
            granularityOptions={meta?.granularities ?? []}
            className="mb-4"
          />
        </Container>

        <Container width="fluid">
          {!workspaceId ? null : reportKey === 'conversations' ? (
            <ConversationsReport workspaceId={workspaceId} filters={scopedFilters} />
          ) : reportKey === 'responses' ? (
            <ResponsesReport
              workspaceId={workspaceId}
              filters={scopedFilters}
              groupBy={groupBy}
              onGroupByChange={setGroupBy}
            />
          ) : reportKey === 'resolutions' ? (
            <ResolutionsReport
              workspaceId={workspaceId}
              filters={scopedFilters}
              groupBy={groupBy}
              onGroupByChange={setGroupBy}
            />
          ) : reportKey === 'messages' ? (
            <MessagesReport
              workspaceId={workspaceId}
              filters={scopedFilters}
              groupBy={groupBy}
              onGroupByChange={setGroupBy}
            />
          ) : reportKey === 'users' ? (
            <UsersReport workspaceId={workspaceId} filters={scopedFilters} />
          ) : reportKey === 'leaderboard' ? (
            <LeaderboardReport workspaceId={workspaceId} filters={scopedFilters} />
          ) : (
            <AssignmentsReport workspaceId={workspaceId} filters={scopedFilters} />
          )}
        </Container>
      </Fragment>
    </RequirePermission>
  );
}
