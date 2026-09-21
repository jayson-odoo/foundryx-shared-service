import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { JobProgress } from './job-progress';

describe('JobProgress (AC-11-27/43)', () => {
  it('renders "Queued…" with no page count before a stage is known', () => {
    render(<JobProgress status="queued" stage={null} pagesDone={null} pagesTotal={null} />);
    expect(screen.getByTestId('job-progress-label')).toHaveTextContent('Queued…');
  });

  it('renders the stage label and page count once known', () => {
    render(<JobProgress status="running" stage="source" pagesDone={3} pagesTotal={12} />);
    expect(screen.getByTestId('job-progress-label')).toHaveTextContent('Reading source · page 3 of 12');
  });

  it('never fabricates a page count when it is not known', () => {
    render(<JobProgress status="running" stage="dry_run" pagesDone={null} pagesTotal={null} />);
    expect(screen.getByTestId('job-progress-label')).toHaveTextContent('Checking with the consumer');
    expect(screen.getByTestId('job-progress-label')).not.toHaveTextContent('page');
  });

  it('labels a lookup stage with its alias', () => {
    render(<JobProgress status="running" stage="lookup:brand" pagesDone={0} pagesTotal={2} />);
    expect(screen.getByTestId('job-progress-label')).toHaveTextContent('Reading lookup brand');
  });

  it('renders every AC-11-27 stage label', () => {
    const cases: Array<[string, string]> = [
      ['combine', 'Combining'],
      ['mapping', 'Mapping'],
      ['storing', 'Storing'],
    ];
    for (const [stage, label] of cases) {
      const { unmount } = render(
        <JobProgress status="running" stage={stage} pagesDone={null} pagesTotal={null} />,
      );
      expect(screen.getByTestId('job-progress-label')).toHaveTextContent(label);
      unmount();
    }
  });

  it('shows "Cancelling…" and hides the Cancel button while cancelling', () => {
    render(
      <JobProgress
        status="cancelling"
        stage="source"
        pagesDone={1}
        pagesTotal={12}
        onCancel={vi.fn()}
      />,
    );
    expect(screen.getByTestId('job-progress-label')).toHaveTextContent('Cancelling…');
    expect(screen.queryByTestId('job-progress-cancel')).not.toBeInTheDocument();
  });

  it('offers a labelled Cancel control while running, and calls onCancel (a11y)', async () => {
    const user = userEvent.setup();
    const onCancel = vi.fn();
    render(
      <JobProgress
        status="running"
        stage="source"
        pagesDone={0}
        pagesTotal={1}
        onCancel={onCancel}
        cancelLabel="Cancel test"
      />,
    );
    const button = screen.getByRole('button', { name: 'Cancel test' });
    await user.click(button);
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it('omits Cancel entirely when the caller offers none (BL-SS-248)', () => {
    render(<JobProgress status="running" stage="source" pagesDone={0} pagesTotal={12} />);
    expect(screen.queryByTestId('job-progress-cancel')).not.toBeInTheDocument();
  });

  it('renders nothing for a terminal status - the caller owns that surface', () => {
    const { container } = render(
      <JobProgress status="done" stage="storing" pagesDone={12} pagesTotal={12} />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
