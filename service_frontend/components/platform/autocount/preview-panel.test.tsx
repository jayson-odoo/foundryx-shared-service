import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { PreviewPanel } from './preview-panel';
import type { AutocountPreviewOk } from '@/types/autocount';

const PREVIEWABLE: AutocountPreviewOk = {
  previewable: true,
  sink: 'sorento',
  summary: { total: 172, created: 134, updated: 38, failed: 0, retryable: 0 },
  predictions: [
    {
      sourceRef: 'AED_VSOFT:3',
      outcome: 'updated',
      entityId: 'sup-3',
      changesLiveData: true,
      diff: {
        payment_terms_days: { current: 30, incoming: null },
        customer_name: { current: 'ONE STOP HOME DESIGN', incoming: 'OW PIN BOON' },
      },
      errors: {},
    },
    {
      sourceRef: 'AED_VSOFT:50',
      outcome: 'created',
      entityId: null,
      changesLiveData: false,
      diff: {},
      errors: {},
    },
    {
      sourceRef: 'AED_VSOFT:51',
      outcome: 'created',
      entityId: null,
      changesLiveData: false,
      diff: {},
      errors: {},
    },
  ],
};

describe('PreviewPanel (AC-14-20/22/26)', () => {
  it('states the total alongside the counts (AC-14-26)', () => {
    render(<PreviewPanel preview={PREVIEWABLE} isLoading={false} error={null} hasRun />);
    const total = screen.getByTestId('preview-stat-total');
    expect(total).toHaveTextContent('172');
    expect(screen.getByTestId('preview-stat-created')).toHaveTextContent('134');
    expect(screen.getByTestId('preview-stat-updated')).toHaveTextContent('38');
  });

  it('renders a value→null blanking row distinctly (AC-14-22)', () => {
    render(<PreviewPanel preview={PREVIEWABLE} isLoading={false} error={null} hasRun />);
    const blanked = screen.getByTestId('prediction-row-payment_terms_days');
    // The destructive case is legible from the DOM, not a paragraph.
    expect(blanked).toHaveAttribute('data-blanking', 'true');
    expect(blanked).toHaveTextContent('Cleared');
    // A plain overwrite (name change) is NOT flagged as a blanking.
    const renamed = screen.getByTestId('prediction-row-customer_name');
    expect(renamed).not.toHaveAttribute('data-blanking');
  });

  it('surfaces the overwrite rows and summarises the creates (AC-14-20)', () => {
    render(<PreviewPanel preview={PREVIEWABLE} isLoading={false} error={null} hasRun />);
    // The one overwrite record is shown as its own card…
    expect(screen.getByTestId('preview-overwrite-AED_VSOFT:3')).toBeInTheDocument();
    // …while the two creates are collapsed into a single count, not listed.
    expect(screen.queryByTestId('preview-overwrite-AED_VSOFT:50')).not.toBeInTheDocument();
    expect(screen.getByTestId('preview-safe-summary')).toHaveTextContent('2 new records');
  });

  it('shows the reason for a not-previewable (logging) sink', () => {
    render(
      <PreviewPanel
        preview={{
          previewable: false,
          sink: 'logging',
          reason: 'No consumer is configured for this company.',
        }}
        isLoading={false}
        error={null}
        hasRun
      />,
    );
    expect(screen.getByTestId('preview-unavailable')).toHaveTextContent(
      'No consumer is configured for this company.',
    );
    expect(screen.queryByTestId('preview-panel')).not.toBeInTheDocument();
  });

  it('shows the dry-run failure message', () => {
    render(
      <PreviewPanel
        preview={null}
        isLoading={false}
        error="The dry run against the consumer failed."
        hasRun
      />,
    );
    expect(screen.getByTestId('preview-error')).toHaveTextContent(
      'The dry run against the consumer failed.',
    );
  });

  it('renders nothing before a preview has been run', () => {
    const { container } = render(
      <PreviewPanel preview={null} isLoading={false} error={null} hasRun={false} />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});

describe('PreviewPanel task variant (plan 22 S2, AC-22-18)', () => {
  it('promotes the overwrite count into the activation-gate strip', () => {
    render(
      <PreviewPanel preview={PREVIEWABLE} isLoading={false} error={null} hasRun variant="task" />,
    );
    expect(screen.getByTestId('preview-stat-extracted')).toHaveTextContent('172');
    expect(screen.getByTestId('preview-stat-would create')).toHaveTextContent('134');
    expect(screen.getByTestId('preview-stat-would update')).toHaveTextContent('38');
    // ONE prediction changes live data in the fixture - the count is derived
    // from the predictions, not a separate vendor number.
    expect(screen.getByTestId('preview-stat-would overwrite')).toHaveTextContent('1');
    expect(screen.getByTestId('preview-stat-would fail')).toHaveTextContent('0');
    expect(screen.queryByTestId('preview-stat-total')).not.toBeInTheDocument();
    // The overwrite cards are the same review surface.
    expect(screen.getByTestId('preview-overwrite-AED_VSOFT:3')).toBeInTheDocument();
  });
});
