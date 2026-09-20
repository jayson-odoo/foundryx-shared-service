import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/lib/api-client';
import type { AutocountCompany, AutocountEntityConfig } from '@/types/autocount';
import { BuildSnapshotDialog } from './build-snapshot-dialog';

const push = vi.fn();
vi.mock('next/navigation', () => ({ useRouter: () => ({ push }) }));

const getCompany = vi.fn();
const buildPullSnapshot = vi.fn();
vi.mock('@/services/autocount-service', () => ({
  autocountService: {
    getCompany: (...a: unknown[]) => getCompany(...a),
    buildPullSnapshot: (...a: unknown[]) => buildPullSnapshot(...a),
  },
}));

// Stub the SearchSelect popover with a plain input keyed on VALUE (never the
// label) - the popover internals aren't under test here, the dialog's own
// entity-filtering + error-slot rendering is (mirrors `connection-form-
// fields.test.tsx`'s established pattern for a SearchSelect nested inside a
// form/dialog, which sidesteps the Radix Popover-inside-Dialog aria-hidden
// timing this suite otherwise fights).
vi.mock('@/components/platform/search-select', () => ({
  SearchSelect: ({
    value,
    onChange,
    ariaLabel,
    options,
  }: {
    value: string | null;
    onChange: (v: string) => void;
    ariaLabel?: string;
    options: { label: string; value: string }[];
  }) => (
    <select aria-label={ariaLabel} value={value ?? ''} onChange={(e) => onChange(e.target.value)}>
      <option value="">{' '}</option>
      {options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  ),
}));

const COMPANIES: AutocountCompany[] = [
  {
    id: 'c1',
    connectionId: 'conn-1',
    databaseName: 'AED',
    companyName: 'AED',
    name: 'AED Sorento',
    isActive: true,
    sinkImpl: 'sorento',
    sinkConnectionId: 'conn-2',
    sorentoCompanyCode: 'SRT',
    createdAt: null,
    sourceKind: 'http',
    documentPrerequisites: [],
  },
  {
    id: 'c2',
    connectionId: 'conn-3',
    databaseName: 'MCH',
    companyName: 'Mocha',
    name: 'Mocha',
    isActive: true,
    sinkImpl: 'sorento',
    sinkConnectionId: 'conn-4',
    sorentoCompanyCode: 'MCH',
    createdAt: null,
    sourceKind: 'http',
    documentPrerequisites: [],
  },
];

function entity(over: Partial<AutocountEntityConfig> = {}): AutocountEntityConfig {
  return {
    id: 'e1',
    entityType: 'product',
    syncMode: 'MANUAL',
    sourceImpl: 'autocount_http',
    recordCap: 5000,
    initialLookbackDays: 30,
    enabled: true,
    lastSuccessAt: null,
    lastAttemptAt: null,
    watermarkAt: null,
    consecutiveFailures: 0,
    lastError: null,
    etlStatus: 'active',
    ...over,
  };
}

beforeEach(() => {
  push.mockReset();
  getCompany.mockReset();
  buildPullSnapshot.mockReset();
});

describe('BuildSnapshotDialog (AC-10-37/50, review round 1 item 2)', () => {
  it('offers only the entities enabled for PULL on the selected company', async () => {
    getCompany.mockResolvedValue({
      company: COMPANIES[0],
      entities: [
        entity({ entityType: 'product', deliveryMode: 'pull' }),
        entity({ entityType: 'supplier', deliveryMode: 'push' }),
        entity({ entityType: 'stock_balance', deliveryMode: 'pull' }),
      ],
    });
    render(<BuildSnapshotDialog open companies={COMPANIES} onOpenChange={vi.fn()} onBuilt={vi.fn()} />);

    fireEvent.change(screen.getByLabelText('Company'), { target: { value: 'c1' } });
    await waitFor(() => expect(getCompany).toHaveBeenCalledWith('c1'));

    const entityOptions = screen.getByLabelText('Entity').querySelectorAll('option');
    const labels = Array.from(entityOptions).map((o) => o.textContent);
    expect(labels).toContain('Product');
    expect(labels).toContain('Stock balance');
    expect(labels).not.toContain('Supplier');
  });

  it('picking a different company clears the previous entity pick', async () => {
    getCompany.mockImplementation(async (id: string) => ({
      company: COMPANIES.find((c) => c.id === id) ?? COMPANIES[0],
      entities: [entity({ entityType: 'product', deliveryMode: 'pull' })],
    }));
    render(<BuildSnapshotDialog open companies={COMPANIES} onOpenChange={vi.fn()} onBuilt={vi.fn()} />);
    fireEvent.change(screen.getByLabelText('Company'), { target: { value: 'c1' } });
    await waitFor(() => expect(getCompany).toHaveBeenCalledWith('c1'));
    fireEvent.change(screen.getByLabelText('Entity'), { target: { value: 'product' } });
    expect(screen.getByLabelText('Entity')).toHaveValue('product');

    fireEvent.change(screen.getByLabelText('Company'), { target: { value: 'c2' } });
    await waitFor(() => expect(getCompany).toHaveBeenCalledWith('c2'));
    expect(screen.getByLabelText('Entity')).toHaveValue('');
  });

  it('a 409 PUSH_ACTIVE is rendered in the dialog error slot, never a silent failure', async () => {
    // The entity is pull-mode at LOAD time (selectable, per the filter) -
    // the 409 simulates the backend's authoritative check racing ahead of
    // this client's own last-seen state (the book flipped to push+active
    // between load and Build).
    getCompany.mockResolvedValue({
      company: COMPANIES[0],
      entities: [entity({ entityType: 'product', deliveryMode: 'pull' })],
    });
    buildPullSnapshot.mockRejectedValue(
      new ApiError('This book is now automatic.', 409, null, {
        code: 'PUSH_ACTIVE',
        message: 'This book is now automatic.',
        companyCode: 'SRT',
        entity: 'products',
      }),
    );
    render(<BuildSnapshotDialog open companies={COMPANIES} onOpenChange={vi.fn()} onBuilt={vi.fn()} />);
    fireEvent.change(screen.getByLabelText('Company'), { target: { value: 'c1' } });
    await waitFor(() => expect(getCompany).toHaveBeenCalled());
    fireEvent.change(screen.getByLabelText('Entity'), { target: { value: 'product' } });
    fireEvent.click(screen.getByRole('button', { name: 'Build' }));

    await waitFor(() => expect(screen.getByText('This book is now automatic.')).toBeInTheDocument());
    expect(push).not.toHaveBeenCalled();
  });
});
