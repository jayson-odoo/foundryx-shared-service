import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { MigrationReport } from '@/types/respondio-migration';
import { MigrationReportCard } from './migration-report-card';

function report(overrides: Partial<MigrationReport> = {}): MigrationReport {
  const zero = { fetched: 0, wouldCreate: 0, wouldUpdate: 0, wouldSkip: 0, errors: 0 };
  return {
    entities: {
      contacts: { fetched: 10, wouldCreate: 8, wouldUpdate: 2, wouldSkip: 0, errors: 0 },
      fields: { ...zero },
      tags: { ...zero },
      identities: { ...zero },
      messages: { ...zero },
      media: { ...zero },
      events: { ...zero },
      quickReplies: { ...zero },
    },
    messagesWithInferredTimestamp: 0,
    messagesSkippedBeforeFloor: 0,
    blockers: [],
    samples: { contacts: [], messages: [] },
    ...overrides,
  };
}

describe('MigrationReportCard (AC-MIG-08)', () => {
  it('renders one DataGrid row per entity with its counts', () => {
    render(<MigrationReportCard report={report()} />);
    expect(screen.getByText('Counts report')).toBeInTheDocument();
    expect(screen.getByRole('table')).toBeInTheDocument();
    expect(screen.getByText('Contacts')).toBeInTheDocument();
    expect(screen.getByText('Custom fields')).toBeInTheDocument();
    expect(screen.getByText('Quick replies')).toBeInTheDocument();
  });

  it('renders the blockers list when present', () => {
    render(<MigrationReportCard report={report({ blockers: ['16 contacts have no lifecycle mapping.'] })} />);
    expect(screen.getByText('16 contacts have no lifecycle mapping.')).toBeInTheDocument();
  });

  it('renders the inferred-timestamp note only when non-zero', () => {
    const { rerender } = render(<MigrationReportCard report={report({ messagesWithInferredTimestamp: 0 })} />);
    expect(screen.queryByText(/message timestamps were inferred/)).not.toBeInTheDocument();
    rerender(<MigrationReportCard report={report({ messagesWithInferredTimestamp: 42 })} />);
    expect(screen.getByText(/42 message timestamps were inferred/)).toBeInTheDocument();
  });

  it('renders the messagesSince-floor note only when non-zero (S4 D-A6-22)', () => {
    const { rerender } = render(<MigrationReportCard report={report({ messagesSkippedBeforeFloor: 0 })} />);
    expect(screen.queryByText(/older than the "Messages since" floor/)).not.toBeInTheDocument();
    rerender(<MigrationReportCard report={report({ messagesSkippedBeforeFloor: 7 })} />);
    expect(screen.getByText(/7 messages were older than the "Messages since" floor/)).toBeInTheDocument();
  });
});
