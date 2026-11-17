/**
 * Crew pass 041306ae: removing the last receiver (right-click menu, after its
 * countdown) left the page on Push with an empty list until a reload.
 */
import { render, screen } from '@testing-library/react';
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

let receiversData: LeadReceiverItem[] | null = [receiver];

vi.mock('@/hooks/use-lead-capture', () => ({
  useReceivers: () => ({ data: receiversData, loading: false, error: null, reload: vi.fn() }),
  useRemoveReceivers: () => ({ removing: false, remove: vi.fn() }),
  leadCaptureErrorMessage: (_e: unknown, f: string) => f,
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
vi.mock('./components/use-receiver-list', () => ({ useReceiverList: () => ({}) }));
vi.mock('./components/add-receiver-dialog', () => ({ AddReceiverDialog: () => null }));
vi.mock('./components/pull-only-panel', () => ({ PullOnlyPanel: () => <div>leads address</div> }));
vi.mock('@/services/lead-capture-service', () => ({ leadsPullUrl: () => 'https://x/leads' }));

describe('Delivery page', () => {
  it('switches to Pull only once the last receiver is gone (no reload)', () => {
    receiversData = [receiver];
    const { rerender } = render(<LeadCaptureDeliveryPage />);
    expect(screen.getByText('receiver list')).toBeInTheDocument();
    // The receivers reload after a committed Remove: a NEW, empty list.
    receiversData = [];
    rerender(<LeadCaptureDeliveryPage />);
    expect(screen.getByText('leads address')).toBeInTheDocument();
    expect(screen.queryByText('receiver list')).not.toBeInTheDocument();
  });
});
