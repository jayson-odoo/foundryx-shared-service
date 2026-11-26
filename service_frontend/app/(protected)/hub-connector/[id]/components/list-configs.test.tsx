import { describe, expect, it, vi } from 'vitest';
import { renderHook } from '@testing-library/react';
import type { HubCustomer, HubDelivery } from '@/types/hub-connector';

vi.mock('@/hooks/use-datetime', () => ({
  useDatetime: () => ({ formatDmyDateTime: (v: string) => v }),
}));
vi.mock('@/services/hub-connector-service', () => ({ hubConnectorService: {} }));
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import { deliveryResult, useDeliveriesListConfig } from './use-deliveries-list-config';
import { useCustomersListConfig } from './use-customers-list-config';

const delivery = (over: Partial<HubDelivery>): HubDelivery => ({
  id: 'd', event: 'availability.updated', customerCode: 'C', customerName: 'Customer', status: 'SUCCESS',
  attempt: 1, lastCode: 200, lastError: null, createdAt: '', lastAttemptAt: null, ...over,
});

describe('deliveries list config', () => {
  it('offers Send again only for a failed delivery', () => {
    const { result } = renderHook(() => useDeliveriesListConfig('h1'));
    const again = result.current.actions.find((a) => a.id === 'send-again');
    expect(again?.isVisible?.([delivery({ status: 'FAILED' })])).toBe(true);
    expect(again?.isVisible?.([delivery({ status: 'SUCCESS' })])).toBe(false);
  });

  it('states the receiver answer in plain words', () => {
    expect(deliveryResult(delivery({ lastError: 'Receiver unavailable' }))).toBe('Receiver unavailable');
    expect(deliveryResult(delivery({ lastCode: 200 }))).toBe('Answered 200');
    expect(deliveryResult(delivery({ lastCode: null }))).toBe('-');
  });
});

describe('customers list config', () => {
  it('has the agreed columns and opens the policy dialog on row click', () => {
    const onEdit = vi.fn();
    const { result } = renderHook(() =>
      useCustomersListConfig({ hubId: 'h1', onCreate: vi.fn(), onEdit, onPreview: vi.fn(), refreshKey: 0 }),
    );
    const ids = result.current.columns.map((c) => c.id);
    expect(ids).toEqual(['customerName', 'customerCode', 'locations', 'brands', 'active', 'updatedAt', 'actions']);
    const row = { id: 'hc' } as HubCustomer;
    result.current.onRowSelect?.(row, 0, [row]);
    expect(onEdit).toHaveBeenCalledWith(row);
    expect(result.current.actions.map((a) => a.id)).toEqual(['edit', 'preview', 'remove']);
  });
});
