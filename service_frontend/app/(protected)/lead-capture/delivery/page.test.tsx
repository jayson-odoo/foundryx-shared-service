/**
 * Crew pass 041306ae: removing the last receiver (right-click menu, after its
 * countdown) left the page on Push with an empty list until a reload. Real
 * receivers hook + a mocked service, so each reload follows the real timing.
 */
import { act, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { LeadReceiverItem } from '@/types/lead-capture';
import LeadCaptureDeliveryPage from './page';

const receiver: LeadReceiverItem = {
  id: 'r1',
  url: 'https://hooks1.example.com/lead-capture',
  events: ['lead.created'],
  createdAt: '2026-11-17T00:00:00Z',
  lastSuccessAt: null,
};

const listReceivers = vi.fn();
let onChanged: () => void = () => {};

vi.mock('@/services/lead-capture-service', () => ({
  leadCaptureService: { listReceivers: () => listReceivers(), removeReceivers: vi.fn() },
  leadsPullUrl: () => 'https://x/leads',
}));
vi.mock('@/hooks/use-can', () => ({ useCan: () => ({ can: () => true }) }));
vi.mock('@/components/common/require-permission', () => ({
  RequirePermission: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));
vi.mock('@/components/common/container', () => ({
  Container: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));
vi.mock('@/components/platform/page-header', () => ({ PageHeader: () => null }));
vi.mock('@/components/platform/resource-list', () => ({ ResourceList: () => <div>receiver list</div> }));
vi.mock('./components/use-receiver-list', () => ({
  // The list's onDeferredCommitted / row-menu reload calls this.
  useReceiverList: (_create: () => void, changed: () => void) => {
    onChanged = changed;
    return {};
  },
}));
vi.mock('./components/add-receiver-dialog', () => ({ AddReceiverDialog: () => null }));
vi.mock('./components/pull-only-panel', () => ({ PullOnlyPanel: () => <div>leads address</div> }));

describe('Delivery page', () => {
  it('switches to Pull only once the last receiver is removed (no reload)', async () => {
    listReceivers.mockResolvedValue([receiver]);
    render(<LeadCaptureDeliveryPage />);
    await screen.findByText('receiver list');

    // A committed Remove of the last receiver: the receivers reload, empty.
    listReceivers.mockResolvedValue([]);
    await act(async () => {
      onChanged();
    });
    await waitFor(() => expect(screen.getByText('leads address')).toBeInTheDocument());
    expect(screen.queryByText('receiver list')).not.toBeInTheDocument();
  });
});
