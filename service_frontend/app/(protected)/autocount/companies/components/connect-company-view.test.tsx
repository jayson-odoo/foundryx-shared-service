import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/lib/api-client';
import type {
  SourceConnectionsState,
  UseAutocountSourceConnectionsResult,
} from '@/hooks/use-autocount-connections';
import type { ResourceFormConfig } from '@/components/platform/resource-form';
import type { AutocountCompany } from '@/types/autocount';

const push = vi.fn();
vi.mock('next/navigation', () => ({ useRouter: () => ({ push }) }));

const toastSuccess = vi.fn();
const toastError = vi.fn();
vi.mock('sonner', () => ({
  toast: { success: (...a: unknown[]) => toastSuccess(...a), error: (...a: unknown[]) => toastError(...a) },
}));

const createCompany = vi.fn();
vi.mock('@/services/autocount-service', () => ({
  autocountService: { createCompany: (...args: unknown[]) => createCompany(...args) },
}));

// The connections hook is the data seam - drive every source state from here.
const sources = vi.fn<() => UseAutocountSourceConnectionsResult>();
vi.mock('@/hooks/use-autocount-connections', () => ({
  useAutocountSourceConnections: () => sources(),
}));

// Layout chrome pulls in providers - passthrough.
vi.mock('@/components/common/container', () => ({
  Container: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

// The shell is covered by its own suite; here it is reduced to what the view
// wires into it - the first tab's body, the Create button (its `saveDisabled`
// gate), and `onSave`.
vi.mock('@/components/platform/resource-form', () => ({
  FormRow: ({ label, children }: { label: string; children: React.ReactNode }) => (
    <div>
      <span>{label}</span>
      {children}
    </div>
  ),
  ResourceForm: ({ config }: { config: ResourceFormConfig<AutocountCompany> }) => (
    <div>
      {config.tabs[0].render({ editing: true })}
      <button type="button" data-testid="create" disabled={config.saveDisabled} onClick={() => void config.onSave()}>
        Create
      </button>
    </div>
  ),
}));

const { ConnectCompanyView } = await import('./connect-company-view');

function state(over: Partial<SourceConnectionsState> = {}): SourceConnectionsState {
  return { options: [], hasAny: false, allBound: false, isLoading: false, ...over };
}

const API_OPTIONS = [{ label: 'AutoCount HQ', value: 'conn-api-1' }];
const DB_OPTIONS = [
  { label: 'SQL HQ · AED_HQ', value: 'conn-sql-1' },
  { label: 'SQL Branch · AED_BRANCH', value: 'conn-sql-2' },
];

function both(): UseAutocountSourceConnectionsResult {
  return {
    api: state({ options: API_OPTIONS, hasAny: true }),
    db: state({ options: DB_OPTIONS, hasAny: true }),
    isLoading: false,
    defaultKind: 'api',
  };
}

function dbOnly(): UseAutocountSourceConnectionsResult {
  return {
    api: state(),
    db: state({ options: DB_OPTIONS, hasAny: true }),
    isLoading: false,
    defaultKind: 'db',
  };
}

function segment(name: string) {
  return screen.getByRole('radio', { name });
}

beforeEach(() => {
  push.mockReset();
  toastSuccess.mockReset();
  toastError.mockReset();
  createCompany.mockReset();
  sources.mockReset().mockReturnValue(both());
});

describe('ConnectCompanyView - Source toggle (AC-01-12)', () => {
  it('offers AutoCount API | SQL database and defaults to API when both have a connection', () => {
    render(<ConnectCompanyView />);
    expect(segment('AutoCount API')).toHaveAttribute('data-state', 'on');
    expect(segment('SQL database')).toHaveAttribute('data-state', 'off');
    expect(screen.getByRole('combobox', { name: 'AutoCount connection' })).toBeInTheDocument();
  });

  it('defaults to SQL database when only it has an unbound connection', () => {
    sources.mockReturnValue(dbOnly());
    render(<ConnectCompanyView />);
    expect(segment('SQL database')).toHaveAttribute('data-state', 'on');
    expect(screen.getByRole('combobox', { name: 'SQL database connection' })).toBeInTheDocument();
  });

  it('the SQL picker lists the source\'s (already-filtered) connections only', () => {
    sources.mockReturnValue(dbOnly());
    render(<ConnectCompanyView />);
    fireEvent.click(screen.getByRole('combobox', { name: 'SQL database connection' }));
    const names = screen.getAllByRole('option').map((o) => o.textContent);
    expect(names).toEqual(['SQL HQ · AED_HQ', 'SQL Branch · AED_BRANCH']);
    expect(names).not.toContain('AutoCount HQ');
  });

  it('switching source clears the picked connection', async () => {
    render(<ConnectCompanyView />);
    fireEvent.click(segment('SQL database'));
    const picker = screen.getByRole('combobox', { name: 'SQL database connection' });
    fireEvent.click(picker);
    fireEvent.click(await screen.findByRole('option', { name: 'SQL Branch · AED_BRANCH' }));
    expect(screen.getByRole('combobox', { name: 'SQL database connection' })).toHaveTextContent(
      'SQL Branch · AED_BRANCH',
    );
    fireEvent.click(segment('AutoCount API'));
    expect(screen.getByRole('combobox', { name: 'AutoCount connection' })).toHaveTextContent(
      'Select a connection',
    );
    expect(screen.getByTestId('create')).toBeDisabled();
  });
});

describe('ConnectCompanyView - per-source banners + Create gate (AC-01-13)', () => {
  it('SQL source with no connection at all: banner + link to Integrations', () => {
    sources.mockReturnValue({
      api: state({ options: API_OPTIONS, hasAny: true }),
      db: state(),
      isLoading: false,
      defaultKind: 'api',
    });
    render(<ConnectCompanyView />);
    fireEvent.click(segment('SQL database'));
    const banner = screen.getByTestId('connect-company-banner');
    expect(banner).toHaveTextContent('No SQL database connection yet.');
    expect(screen.getByRole('link', { name: 'Add one in Integrations' })).toHaveAttribute(
      'href',
      '/settings/integrations/new',
    );
  });

  it('SQL source with every connection bound: the all-bound banner', () => {
    sources.mockReturnValue({
      api: state({ options: API_OPTIONS, hasAny: true }),
      db: state({ hasAny: true, allBound: true }),
      isLoading: false,
      defaultKind: 'api',
    });
    render(<ConnectCompanyView />);
    fireEvent.click(segment('SQL database'));
    expect(screen.getByTestId('connect-company-banner')).toHaveTextContent(
      'Every SQL database connection is already registered as a company.',
    );
  });

  it('the API source keeps today\'s two banners (regression pin)', () => {
    sources.mockReturnValue({ api: state(), db: state({ options: DB_OPTIONS, hasAny: true }), isLoading: false, defaultKind: 'db' });
    render(<ConnectCompanyView />);
    fireEvent.click(segment('AutoCount API'));
    expect(screen.getByTestId('connect-company-banner')).toHaveTextContent(
      'No AutoCount integration is connected yet.',
    );
    sources.mockReturnValue({ api: state({ hasAny: true, allBound: true }), db: state(), isLoading: false, defaultKind: 'api' });
    render(<ConnectCompanyView />);
    expect(
      screen.getByText('Every AutoCount connection is already registered as a company.'),
    ).toBeInTheDocument();
  });

  it('no banner while a source has something to pick', () => {
    render(<ConnectCompanyView />);
    expect(screen.queryByTestId('connect-company-banner')).not.toBeInTheDocument();
  });

  it('Create is disabled until a connection is picked', async () => {
    sources.mockReturnValue(dbOnly());
    render(<ConnectCompanyView />);
    expect(screen.getByTestId('create')).toBeDisabled();
    fireEvent.click(screen.getByRole('combobox', { name: 'SQL database connection' }));
    fireEvent.click(await screen.findByRole('option', { name: 'SQL HQ · AED_HQ' }));
    expect(screen.getByTestId('create')).toBeEnabled();
  });
});

describe('ConnectCompanyView - Create + errors (AC-01-14)', () => {
  async function pickAndCreate(label = 'SQL Branch · AED_BRANCH') {
    sources.mockReturnValue(dbOnly());
    render(<ConnectCompanyView />);
    fireEvent.click(screen.getByRole('combobox', { name: 'SQL database connection' }));
    fireEvent.click(await screen.findByRole('option', { name: label }));
    fireEvent.click(screen.getByTestId('create'));
  }

  it('calls createCompany({connectionId, name}) and routes to the new company', async () => {
    createCompany.mockResolvedValue({ id: 'company-db-1', databaseName: 'AED_BRANCH' });
    await pickAndCreate();
    await waitFor(() => expect(push).toHaveBeenCalledWith('/autocount/companies/company-db-1'));
    expect(createCompany).toHaveBeenCalledWith({ connectionId: 'conn-sql-2', name: '' });
    expect(toastSuccess).toHaveBeenCalledWith('Connected AED_BRANCH.');
  });

  it('renders a 422 on connectionId inline under the picker (probe mismatch / auth failure)', async () => {
    const message = "This login lands on 'AED_OTHER', but the connection names 'AED_BRANCH'.";
    createCompany.mockRejectedValue(
      new ApiError(message, 422, null, { fieldErrors: { connectionId: message } }),
    );
    await pickAndCreate();
    expect(await screen.findByTestId('connection-error')).toHaveTextContent(message);
    expect(push).not.toHaveBeenCalled();
    expect(toastError).not.toHaveBeenCalled();
  });

  it('renders a 409 inline naming the existing company', async () => {
    createCompany.mockRejectedValue(
      new ApiError("'AED_BRANCH' is already connected as company 'Branch'.", 409),
    );
    await pickAndCreate();
    expect(await screen.findByTestId('connection-error')).toHaveTextContent(
      "'AED_BRANCH' is already connected as company 'Branch'.",
    );
    expect(toastError).not.toHaveBeenCalled();
  });

  it('other failures still toast (unchanged)', async () => {
    createCompany.mockRejectedValue(new ApiError('Upstream unavailable.', 502));
    await pickAndCreate();
    await waitFor(() => expect(toastError).toHaveBeenCalledWith('Upstream unavailable.'));
    expect(screen.queryByTestId('connection-error')).not.toBeInTheDocument();
  });
});
