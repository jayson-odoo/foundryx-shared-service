import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { MigrationFailuresTable } from './migration-failures-table';

describe('MigrationFailuresTable (AC-MIG-08)', () => {
  it('renders a DataGrid with one row per failure and the Entity/Reason/Action columns', () => {
    render(
      <MigrationFailuresTable
        jobId="mig-job-001"
        rows={[
          { entity: 'media', sourceId: 'rio-msg-1', sourceLabel: 'image attachment', reason: '404 fetching source URL', action: 'skipped' },
          { entity: 'identity', sourceId: 'rio-cnt-1', sourceLabel: 'Alicia Chan', reason: 'no derivable external id', action: 'skipped' },
        ]}
        totalFailures={2}
      />,
    );
    expect(screen.getByText('Failures (2)')).toBeInTheDocument();
    expect(screen.getByRole('table')).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: 'Entity' })).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: 'Reason' })).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: 'Action taken' })).toBeInTheDocument();
    expect(screen.getByText('404 fetching source URL')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Download CSV/i })).toBeInTheDocument();
  });

  it('renders the empty grid state for zero rows', () => {
    render(<MigrationFailuresTable jobId="mig-job-001" rows={[]} totalFailures={0} />);
    expect(screen.getByText('Failures (0)')).toBeInTheDocument();
  });
});
