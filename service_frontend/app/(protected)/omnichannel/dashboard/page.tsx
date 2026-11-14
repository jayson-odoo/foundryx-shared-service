'use client';

/**
 * Omnichannel Dashboard (plan 30, roadmap A9, AC-RPT-42) - current state
 * tiles, lifecycle stages, opened-vs-closed trend, response/resolution
 * medians and top agents over the shared filter bar. Workspace resolves
 * exactly like Contacts (D-A9-16); gated `reports.read` (the main-session
 * override of D-A9-10's `conversation_reports.read`).
 */
import { Fragment } from 'react';
import { LoaderCircleIcon } from 'lucide-react';
import { Container } from '@/components/common/container';
import { RequirePermission } from '@/components/common/require-permission';
import { PageHeader } from '@/components/platform/page-header';
import { SearchSelect } from '@/components/platform/search-select';
import { useActiveWorkspace } from '@/hooks/use-contacts';
import { useOmnichannelDashboard } from '@/hooks/use-omnichannel-dashboard';
import { useReportFilters } from '@/hooks/use-report-filters';
import { useReportMeta } from '@/hooks/use-report-meta';
import { useWorkspaceChannels } from '@/hooks/use-workspace-channels';
import { useWorkspaceMembers } from '@/hooks/use-workspace-members';
import { DurationStatCard } from '../components/duration-stat-card';
import { ReportFilterBar } from '../components/report-filter-bar';
import { LifecycleTiles } from './components/lifecycle-tiles';
import { OpenedClosedCard } from './components/opened-closed-card';
import { StateTiles } from './components/state-tiles';
import { TopAgentsCard } from './components/top-agents-card';

export default function OmnichannelDashboardPage() {
  const { workspaceId, workspaces, ready, setWorkspaceId } = useActiveWorkspace();
  const { members } = useWorkspaceMembers(workspaceId);
  const { meta } = useReportMeta(workspaceId);
  const { state, setDateRange, setUserId, setChannelId, setGranularity, filters } = useReportFilters();
  const { dashboard, loading, error } = useOmnichannelDashboard(workspaceId, filters);

  const { options: channelOptions } = useWorkspaceChannels(workspaceId);

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
            granularityOptions={meta?.granularities ?? ['hour', 'day', 'week', 'month']}
            className="mb-4"
          />
        </Container>

        <Container width="fluid">
          {loading || !dashboard ? (
            <div className="flex items-center justify-center py-24 text-muted-foreground">
              <LoaderCircleIcon className="size-6 animate-spin" />
            </div>
          ) : error ? (
            <div className="flex items-center justify-center py-24 text-sm text-muted-foreground">
              Couldn&apos;t load the dashboard.
            </div>
          ) : (
            <div className="flex flex-col gap-4">
              <StateTiles tiles={dashboard.tiles} />
              <LifecycleTiles stages={dashboard.lifecycle} />
              <OpenedClosedCard buckets={dashboard.buckets} series={dashboard.series} />
              <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                <DurationStatCard title="First response time" stats={dashboard.responseTotals} />
                <DurationStatCard title="Resolution time" stats={dashboard.resolutionTotals} />
              </div>
              <TopAgentsCard agents={dashboard.topAgents} />
            </div>
          )}
        </Container>
      </Fragment>
    </RequirePermission>
  );
}
