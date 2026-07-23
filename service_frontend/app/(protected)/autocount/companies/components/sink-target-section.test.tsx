import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { AutocountCompany } from '@/types/autocount';

const consumerConnections = vi.fn();
vi.mock('@/hooks/use-autocount-consumer-connections', () => ({
  useAutocountConsumerConnections: () => consumerConnections(),
}));

const { SinkTargetSection } = await import('./sink-target-section');

function company(over: Partial<AutocountCompany> = {}): AutocountCompany {
  return {
    id: 'c1',
    connectionId: 'conn-1',
    databaseName: 'AED_VSOFT',
    companyName: 'V Soft',
    name: 'V Soft',
    isActive: true,
    sinkImpl: 'sorento',
    sinkConnectionId: 'conn-9',
    createdAt: null,
    ...over,
  };
}

beforeEach(() => {
  consumerConnections.mockReset().mockReturnValue({
    options: [{ label: 'Sorento prod', value: 'conn-9' }],
    isLoading: false,
    emptyReason: null,
  });
});

describe('push target — read vs edit (AC-15-20/21)', () => {
  it('read mode shows plain label/value, no dropdowns and no Save', () => {
    render(
      <SinkTargetSection
        company={company()}
        editing={false}
        sinkImpl="sorento"
        connectionId="conn-9"
        onSinkChange={vi.fn()}
        onConnectionChange={vi.fn()}
      />,
    );
    expect(screen.getByText('Sorento')).toBeInTheDocument();
    expect(screen.getByText('Sorento prod')).toBeInTheDocument();
    // No editable control and no detached Save in read mode.
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /save/i })).not.toBeInTheDocument();
  });

  it('edit mode exposes the searchable delivery + connection pickers', () => {
    render(
      <SinkTargetSection
        company={company()}
        editing
        sinkImpl="sorento"
        connectionId="conn-9"
        onSinkChange={vi.fn()}
        onConnectionChange={vi.fn()}
      />,
    );
    // Two SearchSelects (delivery + connection) in edit mode.
    expect(screen.getAllByRole('combobox').length).toBeGreaterThanOrEqual(2);
  });

  it('warns (foolproof-UI) when Sorento is chosen with no connection', () => {
    render(
      <SinkTargetSection
        company={company({ sinkImpl: 'logging', sinkConnectionId: null })}
        editing
        sinkImpl="sorento"
        connectionId={null}
        onSinkChange={vi.fn()}
        onConnectionChange={vi.fn()}
      />,
    );
    expect(screen.getByTestId('sink-connection-warning')).toBeInTheDocument();
  });

  it('surfaces the no-connection prerequisite when none is configured', () => {
    consumerConnections.mockReturnValue({
      options: [],
      isLoading: false,
      emptyReason: 'No Sorento consumer connection is connected yet.',
    });
    render(
      <SinkTargetSection
        company={company({ sinkImpl: 'logging', sinkConnectionId: null })}
        editing
        sinkImpl="sorento"
        connectionId={null}
        onSinkChange={vi.fn()}
        onConnectionChange={vi.fn()}
      />,
    );
    expect(screen.getByTestId('sink-connection-warning')).toHaveTextContent(
      /No Sorento consumer connection/i,
    );
  });

  it('hides the connection row for a logging company', () => {
    render(
      <SinkTargetSection
        company={company({ sinkImpl: 'logging', sinkConnectionId: null })}
        editing={false}
        sinkImpl="logging"
        connectionId={null}
        onSinkChange={vi.fn()}
        onConnectionChange={vi.fn()}
      />,
    );
    expect(screen.getByText('No delivery (logging only)')).toBeInTheDocument();
    expect(screen.queryByText('Sorento connection')).not.toBeInTheDocument();
  });
});
