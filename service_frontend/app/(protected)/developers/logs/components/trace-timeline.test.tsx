/**
 * Trace timeline (sprint-4/12 Slice 2, AC-DLC-18) - renders the correlated legs
 * of one consumption with source/status badges + latency, links each leg to its
 * detail, and highlights the currently-viewed leg.
 */
import { render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { IntegrationLogItem } from '@/types/integration-logs';

const svc = { getTrace: vi.fn() };
vi.mock('@/services/integration-log-service', () => ({
  get integrationLogService() {
    return svc;
  },
}));
vi.mock('@/hooks/use-datetime', () => ({
  useDatetime: () => ({ formatDateTime: (iso: string) => `at ${iso}` }),
}));

import { TraceTimeline } from './trace-timeline';

function leg(over: Partial<IntegrationLogItem>): IntegrationLogItem {
  return {
    id: 'l1',
    tenantId: 't',
    traceId: 'trace-1',
    source: 'inbound_api',
    workspaceId: null,
    apiKeyId: null,
    operation: 'POST /messages',
    method: 'POST',
    status: 'success',
    statusCode: 200,
    errorCode: null,
    latencyMs: 12,
    externalRef: null,
    createdAt: '2026-07-11T12:00:00Z',
    ...over,
  };
}

describe('TraceTimeline', () => {
  it('renders the ordered legs with badges + latency and links each to its detail', async () => {
    svc.getTrace.mockResolvedValue({
      traceId: 'trace-1',
      legs: [
        leg({ id: 'l1', source: 'inbound_api', operation: 'POST /messages' }),
        leg({ id: 'l2', source: 'outbound_meta', operation: 'graph:send', latencyMs: 42 }),
        leg({
          id: 'l3',
          source: 'webhook_delivery',
          operation: 'webhook:message.status',
          status: 'error',
        }),
      ],
    });

    render(<TraceTimeline traceId="trace-1" currentId="l2" />);

    await waitFor(() => expect(screen.getByTestId('trace-timeline')).toBeInTheDocument());

    // All three legs render, each an anchor to its detail page.
    const links = screen.getAllByRole('link');
    expect(links).toHaveLength(3);
    expect(links[0]).toHaveAttribute('href', '/developers/logs/l1');
    expect(links[1]).toHaveAttribute('href', '/developers/logs/l2');
    expect(links[2]).toHaveAttribute('href', '/developers/logs/l3');

    expect(screen.getByText('graph:send')).toBeInTheDocument();
    expect(screen.getByText('42 ms')).toBeInTheDocument();

    // The currently-viewed leg is marked current.
    expect(links[1]).toHaveAttribute('aria-current', 'true');
    expect(links[0]).not.toHaveAttribute('aria-current');
  });

  it('shows a friendly message when there is no trace', () => {
    render(<TraceTimeline traceId={null} currentId="l1" />);
    expect(screen.getByText(/not part of a correlated trace/i)).toBeInTheDocument();
  });

  it('shows an empty-state when the trace has no legs', async () => {
    svc.getTrace.mockResolvedValue({ traceId: 'trace-x', legs: [] });
    render(<TraceTimeline traceId="trace-x" currentId="l1" />);
    await waitFor(() =>
      expect(screen.getByText(/no correlated legs/i)).toBeInTheDocument(),
    );
  });
});
