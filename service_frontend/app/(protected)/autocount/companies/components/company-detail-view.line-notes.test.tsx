import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ResourceFormConfig } from '@/components/platform/resource-form';
import type { AutocountCompany, AutocountCompanyDetail } from '@/types/autocount';

/**
 * Plan 74 AC-74-04 (RED): the "Line notes database" setting on the company detail screen. A SearchSelect over the
 * tenant's `sql_database` connections (`listSqlConnections`) plus a clear option, saved through the form's single
 * save with `autocountService.updateLineNotesConnection(companyId, { connectionId })` (`null` clears). Shown only
 * when the company is `writeEnabled`. A 422 shows its plain message next to the field. No hint copy.
 *
 * The form shell is reduced to "render the Overview tab in edit mode + a Save button that runs config.onSave", and
 * `SearchSelect` to a native select (the shell's own behaviour is covered elsewhere).
 */

const push = vi.fn();
vi.mock('next/navigation', () => ({ useRouter: () => ({ push }) }));
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock('@/hooks/use-can', () => ({ useCan: () => ({ can: () => true, ready: true }) }));
vi.mock('@/hooks/use-datetime', () => ({
  useDatetime: () => ({
    formatDate: (v: string) => v,
    formatDateTime: (v: string) => v,
    formatTime: (v: string) => v,
  }),
}));

const service = vi.hoisted(() => ({
  listSqlConnections: vi.fn(),
  listApiConnections: vi.fn(),
  listCompanies: vi.fn(),
  updateLineNotesConnection: vi.fn(),
  updateSinkTarget: vi.fn(),
}));
vi.mock('@/services/autocount-service', () => ({ autocountService: service }));
vi.mock('@/hooks/use-autocount-consumer-connections', () => ({
  useAutocountConsumerConnections: () => ({ options: [], isLoading: false, emptyReason: null }),
}));
vi.mock('@/components/common/container', () => ({
  Container: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));
vi.mock('@/components/platform/clamped-text', () => ({
  ClampedText: ({ text }: { text: string }) => <span>{text}</span>,
}));
vi.mock('@/components/platform/resource-list', () => ({
  ResourceList: () => <div data-testid="entities-list" />,
}));
vi.mock('@/components/platform/search-select', () => ({
  SearchSelect: ({
    options,
    value,
    onChange,
    ariaLabel,
    disabled,
  }: {
    options?: { label: string; value: string }[];
    value: string | null;
    onChange: (v: string | null) => void;
    ariaLabel?: string;
    disabled?: boolean;
  }) => (
    <select
      aria-label={ariaLabel}
      disabled={disabled}
      value={value ?? ''}
      onChange={(e) => onChange(e.target.value === '' ? null : e.target.value)}
    >
      <option value="">None</option>
      {(options ?? []).map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  ),
}));
vi.mock('@/components/platform/resource-form', () => ({
  ResourceForm: ({ config }: { config: ResourceFormConfig<AutocountCompany> }) => (
    <div>
      {config.tabs
        .filter((tab) => tab.id === 'overview')
        .map((tab) => (
          <section key={tab.id} data-testid={`tab-${tab.id}`}>
            {tab.render({ editing: true })}
          </section>
        ))}
      <button type="button" onClick={() => void config.onSave()}>
        Save changes
      </button>
    </div>
  ),
}));
vi.mock('./use-runs-list-config', () => ({ useAutocountRunsListConfig: () => ({}) }));
vi.mock('./doc-feeds-tab', () => ({ DocFeedsTab: () => null }));
vi.mock('@/hooks/use-terminology', () => ({
  useTerminology: () => ({
    ready: true,
    label: (k: string) => k,
    labelPlural: (k: string) => k,
    t: (k: string) => k,
    refetch: vi.fn(),
  }),
}));

const detailBox = vi.hoisted(() => ({ current: null as unknown }));
const reload = vi.hoisted(() => vi.fn());
vi.mock('@/hooks/use-autocount-company', () => ({
  useAutocountCompany: () => ({ detail: detailBox.current, isLoading: false, notFound: false, reload }),
}));

const { ApiError } = await import('@/lib/api-client');
const { AutocountCompanyDetailView } = await import('./company-detail-view');

function company(over: Record<string, unknown> = {}): AutocountCompany {
  return {
    id: 'c1',
    connectionId: 'conn-1',
    databaseName: 'AED_VSOFT',
    companyName: 'V Soft',
    name: 'V Soft',
    isActive: true,
    sinkImpl: 'logging',
    sinkConnectionId: null,
    sorentoCompanyCode: null,
    createdAt: null,
    sourceKind: 'api',
    documentPrerequisites: [],
    lineNotesConnectionId: null,
    writeEnabled: true,
    ...over,
  } as AutocountCompany;
}

function show(over: Record<string, unknown> = {}) {
  detailBox.current = { company: company(over), entities: [] } as AutocountCompanyDetail;
  return render(<AutocountCompanyDetailView companyId="c1" />);
}

const FIELD = /line notes database/i;

beforeEach(() => {
  push.mockReset();
  reload.mockReset();
  service.listSqlConnections.mockReset().mockResolvedValue([
    { id: 'sql-1', name: 'AutoCount DB', dialect: 'mssql', database: 'AED_VSOFT' },
    { id: 'sql-2', name: 'Replica DB', dialect: 'mssql', database: 'AED_REPL' },
  ]);
  service.listApiConnections.mockReset().mockResolvedValue([]);
  service.listCompanies.mockReset().mockResolvedValue({ data: [], total: 0, page: 0 });
  service.updateLineNotesConnection.mockReset().mockResolvedValue(company());
  service.updateSinkTarget.mockReset().mockResolvedValue(company());
});

describe('company detail - Line notes database (AC-74-04)', () => {
  it('is hidden when the company is not write enabled', async () => {
    show({ writeEnabled: false });
    await waitFor(() => expect(screen.getByTestId('tab-overview')).toBeInTheDocument());
    expect(screen.queryByLabelText(FIELD)).not.toBeInTheDocument();
    expect(screen.queryByText(FIELD)).not.toBeInTheDocument();
  });

  it('lists the tenant sql_database connections and the saved one is selected', async () => {
    show({ lineNotesConnectionId: 'sql-2' });
    const select = (await screen.findByLabelText(FIELD)) as HTMLSelectElement;
    await waitFor(() => expect(within(select).getAllByRole('option').length).toBeGreaterThan(1));
    expect(service.listSqlConnections).toHaveBeenCalled();
    expect(screen.getByRole('option', { name: /AutoCount DB/ })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: /Replica DB/ })).toBeInTheDocument();
    expect(select.value).toBe('sql-2');
  });

  it('saving calls updateLineNotesConnection(companyId, { connectionId }) and reloads', async () => {
    show();
    const select = await screen.findByLabelText(FIELD);
    await waitFor(() => expect(screen.getByRole('option', { name: /AutoCount DB/ })).toBeInTheDocument());
    fireEvent.change(select, { target: { value: 'sql-1' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    await waitFor(() =>
      expect(service.updateLineNotesConnection).toHaveBeenCalledWith('c1', { connectionId: 'sql-1' }),
    );
    await waitFor(() => expect(reload).toHaveBeenCalled());
  });

  it('clearing sends connectionId null', async () => {
    show({ lineNotesConnectionId: 'sql-1' });
    const select = await screen.findByLabelText(FIELD);
    await waitFor(() => expect(screen.getByRole('option', { name: /AutoCount DB/ })).toBeInTheDocument());
    fireEvent.change(select, { target: { value: '' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    await waitFor(() =>
      expect(service.updateLineNotesConnection).toHaveBeenCalledWith('c1', { connectionId: null }),
    );
  });

  it('does not call the route when the value did not change', async () => {
    show({ lineNotesConnectionId: 'sql-1' });
    await screen.findByLabelText(FIELD);
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    await new Promise((r) => setTimeout(r, 20));
    expect(service.updateLineNotesConnection).not.toHaveBeenCalled();
  });

  it('a 422 shows its plain message next to the field', async () => {
    service.updateLineNotesConnection.mockRejectedValue(
      new ApiError('Choose a database connection of this tenant.', 422),
    );
    show();
    const select = await screen.findByLabelText(FIELD);
    await waitFor(() => expect(screen.getByRole('option', { name: /AutoCount DB/ })).toBeInTheDocument());
    fireEvent.change(select, { target: { value: 'sql-1' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    expect(await screen.findByText('Choose a database connection of this tenant.')).toBeInTheDocument();
    expect(reload).not.toHaveBeenCalled();
  });
});

describe('company detail - Line notes database save order (round 1)', () => {
  it('a failing Sorento check sends no line notes PATCH', async () => {
    show({ sinkImpl: 'sorento', sinkConnectionId: null, sorentoCompanyCode: 'ABC' });
    const select = await screen.findByLabelText(FIELD);
    await waitFor(() => expect(screen.getByRole('option', { name: /AutoCount DB/ })).toBeInTheDocument());
    fireEvent.change(select, { target: { value: 'sql-1' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    await new Promise((r) => setTimeout(r, 20));
    expect(service.updateLineNotesConnection).not.toHaveBeenCalled();
  });

  it('line notes saved then the push target fails: reloads and keeps the saved value', async () => {
    service.updateSinkTarget.mockRejectedValue(new ApiError('Push target refused.', 422));
    show({ sinkImpl: 'sorento', sinkConnectionId: 'sc-1', sorentoCompanyCode: 'ABC' });
    const select = (await screen.findByLabelText(FIELD)) as HTMLSelectElement;
    await waitFor(() => expect(screen.getByRole('option', { name: /AutoCount DB/ })).toBeInTheDocument());
    fireEvent.change(screen.getByTestId('sink-company-code'), { target: { value: 'XYZ' } });
    fireEvent.change(select, { target: { value: 'sql-1' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    await waitFor(() => expect(service.updateLineNotesConnection).toHaveBeenCalledWith('c1', { connectionId: 'sql-1' }));
    await waitFor(() => expect(reload).toHaveBeenCalled());
    expect(select.value).toBe('sql-1');
  });

  it('a saved connection that is no longer listed reads "Connection not found", not unset', async () => {
    show({ lineNotesConnectionId: 'deleted-conn' });
    const select = (await screen.findByLabelText(FIELD)) as HTMLSelectElement;
    await waitFor(() => expect(screen.getByRole('option', { name: /AutoCount DB/ })).toBeInTheDocument());
    expect(screen.getByRole('option', { name: 'Connection not found' })).toBeInTheDocument();
    expect(select.value).toBe('deleted-conn');
  });
});
