'use client';

/**
 * Omnichannel Reports (plan 30, roadmap A9, AC-RPT-44) - a report
 * `SearchSelect` over the shared filter bar, backing all seven reports.
 * Workspace resolves exactly like Contacts/Dashboard (D-A9-16); gated
 * `reports.read` (main-session override of D-A9-10).
 */
import { Fragment, useEffect, useState } from 'react';
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
import { useWorkspaceMembers } from '@/hooks/use-workspace-members';
import { channelService } from '@/services/channel-service';
import type { Channel, ReportKey } from '@/types/omnichannel';
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
  const { meta } = useReportMeta(workspaceId);
  const { state, setDateRange, setUserId, setChannelId, setGranularity, filters } = useReportFilters();
  const [reportKey, setReportKey] = useState<ReportKey>(() => readReportKeyFromUrl());

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const url = new URL(window.location.href);
    url.searchParams.set('report', reportKey);
    window.history.replaceState(null, '', url);
  }, [reportKey]);

  const [channels, setChannels] = useState<Channel[]>([]);
  useEffect(() => {
    if (!workspaceId) return;
    channelService
      .listByWorkspace(workspaceId)
      .then(setChannels)
      .catch(() => setChannels([]));
  }, [workspaceId]);

  const { exporting, runExport } = useReportExport(workspaceId, reportKey, filters);
  const currentDescriptor = meta?.reports.find((r) => r.key === reportKey);
  const canExport = can('reports.export');

  if (!ready) {
    return (
      <Container width="fluid">
        <div className="flex items-center justify-center py-24 text-muted-foreground">
          <LoaderCircleIcon className="size-6 animate-spin" />
        </div>
      </Container>
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
            <ReportPicker
              value={reportKey}
              onChange={setReportKey}
              reports={
                meta?.reports ?? [
                  { key: 'conversations', label: 'Conversations', supportsGroupBy: [], paginated: false, exportable: true },
                  { key: 'responses', label: 'Responses', supportsGroupBy: ['user'], paginated: false, exportable: true },
                  { key: 'resolutions', label: 'Resolutions', supportsGroupBy: ['user'], paginated: false, exportable: true },
                  { key: 'messages', label: 'Messages', supportsGroupBy: ['channel'], paginated: false, exportable: true },
                  { key: 'users', label: 'Users', supportsGroupBy: [], paginated: true, exportable: true },
                  { key: 'leaderboard', label: 'Leaderboard', supportsGroupBy: [], paginated: true, exportable: true },
                  { key: 'assignments', label: 'Assignment log', supportsGroupBy: [], paginated: true, exportable: true },
                ]
              }
            />
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
            channels={channels.map((c) => ({ id: c.id, name: c.name }))}
            granularity={state.granularity}
            onGranularityChange={setGranularity}
            granularityOptions={meta?.granularities ?? ['hour', 'day', 'week', 'month']}
            className="mb-4"
          />
        </Container>

        <Container width="fluid">
          {!workspaceId ? null : reportKey === 'conversations' ? (
            <ConversationsReport workspaceId={workspaceId} filters={filters} />
          ) : reportKey === 'responses' ? (
            <ResponsesReport workspaceId={workspaceId} filters={filters} />
          ) : reportKey === 'resolutions' ? (
            <ResolutionsReport workspaceId={workspaceId} filters={filters} />
          ) : reportKey === 'messages' ? (
            <MessagesReport workspaceId={workspaceId} filters={filters} />
          ) : reportKey === 'users' ? (
            <UsersReport workspaceId={workspaceId} filters={filters} />
          ) : reportKey === 'leaderboard' ? (
            <LeaderboardReport workspaceId={workspaceId} filters={filters} />
          ) : (
            <AssignmentsReport workspaceId={workspaceId} filters={filters} />
          )}
        </Container>
      </Fragment>
    </RequirePermission>
  );
}
