import { fireEvent, render, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  MOCK_REDATED_DOC_NO,
  mockAutocountDocLookupService as svc,
  resetMockDocLookup,
} from '@/services/autocount-doc-lookup-service.mock';
import { DocResult } from './doc-result';

vi.mock('@/hooks/use-datetime', () => ({
  useDatetime: () => ({
    timeZone: 'UTC',
    formatDate: (v: string) => v ?? '',
    formatDateTime: (v: string) => v ?? '',
    formatTime: (v: string) => v ?? '',
  }),
}));

beforeEach(() => resetMockDocLookup());

async function redated() {
  const job = await svc.start({ companyId: 'c1', docNo: MOCK_REDATED_DOC_NO });
  const stored = await svc.stored('c1', MOCK_REDATED_DOC_NO);
  return { result: job.result!, stored };
}

describe('DocResult (AC-17-29/30)', () => {
  it('shows the re-date warning with who and when', async () => {
    const { result, stored } = await redated();
    render(<DocResult result={result} stored={stored} typeLabel="Delivery order" />);
    const banner = screen.getByTestId('ac-find-redated');
    expect(banner).toHaveTextContent('DocDate changed from 01 Oct 2026 to 05 Oct 2026');
    expect(banner).toHaveTextContent('by AIN on 01 Oct 2026, 07:39');
    expect(banner).toHaveTextContent('A pull for 01 Oct 2026 no longer returns this document');
    expect(screen.getByTestId('ac-find-current-date')).toHaveTextContent('05 Oct 2026');
  });

  it('shows the curated facts and the line total', async () => {
    const { result, stored } = await redated();
    render(<DocResult result={result} stored={stored} typeLabel="Delivery order" />);
    expect(screen.getByText('300-R009 · Anon Trading Sdn Bhd')).toBeInTheDocument();
    expect(screen.getByText('MYR 1,250.00')).toBeInTheDocument();
    expect(screen.getByText('ACC-SW2002')).toBeInTheDocument();
    expect(screen.getByTestId('ac-find-lines-total')).toHaveTextContent('1,250.00');
  });

  it('lists each snapshot with the DocDate it had and whether today’s DocDate is in its range', async () => {
    const { result, stored } = await redated();
    render(<DocResult result={result} stored={stored} typeLabel="Delivery order" />);
    fireEvent.mouseDown(screen.getByRole('tab', { name: /seen in snapshots/i }));
    fireEvent.click(screen.getByRole('tab', { name: /seen in snapshots/i }));
    const row = screen.getByRole('link', { name: /c41e0000/i }).closest('tr')!;
    expect(row).toHaveAttribute('class');
    expect(within(row).getByText('No')).toBeInTheDocument();
    expect(within(row).getAllByText('01 Oct 2026').length).toBeGreaterThan(0);
  });

  it('marks a cancelled document', async () => {
    const { result, stored } = await redated();
    const cancelled = { ...result, current: { ...result.current!, cancelled: true }, redated: null };
    render(<DocResult result={cancelled} stored={stored} typeLabel="Delivery order" />);
    expect(screen.getAllByText('Cancelled').length).toBeGreaterThan(0);
    expect(screen.queryByTestId('ac-find-redated')).not.toBeInTheDocument();
  });
});
