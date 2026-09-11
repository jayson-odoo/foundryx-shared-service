import { fireEvent, render, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ResourceFormConfig } from '@/components/platform/resource-form';
import type { AutocountCompany, AutocountCompanyDetail, AutocountEntityConfig } from '@/types/autocount';

/**
 * Company detail on a DB company (plan sprint-5/01, AC-01-16/17/20): the
 * Integration row states the KIND, Add entity offers the kind's catalogue,
 * and the prerequisite card sits above the Entities list. `ResourceForm` is
 * reduced to "render every tab body" - the shell's own behaviour is covered
 * elsewhere; the point here is what the VIEW puts into it.
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
vi.mock('@/services/autocount-service', () => ({ autocountService: {} }));
vi.mock('@/components/common/container', () => ({
  Container: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));
vi.mock('@/components/platform/clamped-text', () => ({
  ClampedText: ({ text }: { text: string }) => <span>{text}</span>,
}));
vi.mock('@/components/platform/resource-list', () => ({
  ResourceList: () => <div data-testid="entities-list" />,
}));
vi.mock('@/components/platform/resource-form', () => ({
  ResourceForm: ({ config }: { config: ResourceFormConfig<AutocountCompany> }) => (
    <div>
      {config.tabs.map((tab) => (
        <section key={tab.id} data-testid={`tab-${tab.id}`}>
          {tab.render({ editing: false })}
        </section>
      ))}
    </div>
  ),
}));
vi.mock('./use-runs-list-config', () => ({ useAutocountRunsListConfig: () => ({}) }));
vi.mock('./sink-target-section', () => ({ SinkTargetSection: () => null }));
function humanize(key: string) {
  return key.split('_').map((p) => p.charAt(0).toUpperCase() + p.slice(1)).join(' ');
}
vi.mock('@/hooks/use-terminology', () => ({
  useTerminology: () => ({
    ready: true,
    label: humanize,
    labelPlural: (k: string) => `${humanize(k)}s`,
    t: humanize,
    refetch: vi.fn(),
  }),
}));

const detailBox = vi.hoisted(() => ({ current: null as unknown }));
vi.mock('@/hooks/use-autocount-company', () => ({
  useAutocountCompany: () => ({
    detail: detailBox.current,
    isLoading: false,
    notFound: false,
    reload: vi.fn(),
  }),
}));

const { AutocountCompanyDetailView } = await import('./company-detail-view');

function company(over: Partial<AutocountCompany> = {}): AutocountCompany {
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
    ...over,
  };
}

function entity(entityType: string, sourceImpl = 'sql_db'): AutocountEntityConfig {
  return {
    id: entityType,
    entityType,
    syncMode: 'AUTO',
    sourceImpl,
    recordCap: 200,
    initialLookbackDays: 30,
    enabled: true,
    lastSuccessAt: null,
    lastAttemptAt: null,
    watermarkAt: null,
    consecutiveFailures: 0,
    lastError: null,
    etlStatus: 'active',
  };
}

function detail(over: Partial<AutocountCompany> = {}, entities: AutocountEntityConfig[] = []): AutocountCompanyDetail {
  return { company: company(over), entities };
}

beforeEach(() => {
  push.mockReset();
  detailBox.current = detail();
});

describe('AutocountCompanyDetailView - kind (AC-01-16, AC-08-10)', () => {
  it('an API (basic-auth) company\'s Integration row reads "API (basic auth)" and still links the connection', () => {
    render(<AutocountCompanyDetailView companyId="c1" />);
    expect(screen.getByTestId('company-source-kind')).toHaveTextContent('API (basic auth)');
    expect(screen.getByRole('link', { name: 'Open connection' })).toHaveAttribute(
      'href',
      '/settings/integrations/conn-1',
    );
  });

  it('a DB company\'s Integration row reads "Database"', () => {
    detailBox.current = detail({ sourceKind: 'db', connectionId: 'conn-sql-1' });
    render(<AutocountCompanyDetailView companyId="c1" />);
    expect(screen.getByTestId('company-source-kind')).toHaveTextContent('Database');
    expect(screen.getByRole('link', { name: 'Open connection' })).toHaveAttribute(
      'href',
      '/settings/integrations/conn-sql-1',
    );
  });

  it('an open (http) company\'s Integration row reads "API (no auth)"', () => {
    detailBox.current = detail({ sourceKind: 'http', connectionId: 'conn-api-mocha' });
    render(<AutocountCompanyDetailView companyId="c1" />);
    expect(screen.getByTestId('company-source-kind')).toHaveTextContent('API (no auth)');
  });
});

describe('AutocountCompanyDetailView - Add entity per kind (AC-01-17, AC-08-18)', () => {
  it('a DB company offers Customer and Supplier, never GRN', () => {
    detailBox.current = detail({ sourceKind: 'db' });
    render(<AutocountCompanyDetailView companyId="c1" />);
    fireEvent.click(screen.getByRole('combobox', { name: 'Add entity' }));
    const names = screen.getAllByRole('option').map((o) => o.textContent);
    expect(names).toHaveLength(10);
    expect(names).toEqual(expect.arrayContaining(['Customer', 'Supplier']));
    expect(names).not.toContain('Goods received note');
  });

  it('an open (http) company offers exactly the six confirmed open-API masters', () => {
    detailBox.current = detail({ sourceKind: 'http', connectionId: 'conn-api-mocha' });
    render(<AutocountCompanyDetailView companyId="c1" />);
    fireEvent.click(screen.getByRole('combobox', { name: 'Add entity' }));
    const names = screen.getAllByRole('option').map((o) => o.textContent);
    expect(names).toHaveLength(6);
    expect(names).toEqual(
      expect.arrayContaining(['Product', 'Customer', 'Warehouse', 'Product category', 'Brand', 'Unit of measure']),
    );
  });

  it('an API company keeps today\'s seven', () => {
    render(<AutocountCompanyDetailView companyId="c1" />);
    fireEvent.click(screen.getByRole('combobox', { name: 'Add entity' }));
    const names = screen.getAllByRole('option').map((o) => o.textContent);
    expect(names).toHaveLength(7);
    expect(names).not.toContain('Customer');
  });
});

describe('AutocountCompanyDetailView - prerequisite card (AC-01-20)', () => {
  it('is absent when no document entity is configured', () => {
    detailBox.current = detail({ sourceKind: 'db' }, [entity('customer')]);
    render(<AutocountCompanyDetailView companyId="c1" />);
    expect(screen.queryByTestId('document-prerequisites')).not.toBeInTheDocument();
  });

  it('is absent when every prerequisite is active', () => {
    detailBox.current = detail(
      { sourceKind: 'db', documentPrerequisites: [{ entityType: 'sales_order', missing: [], inactive: [] }] },
      [entity('customer'), entity('product'), entity('sales_order')],
    );
    render(<AutocountCompanyDetailView companyId="c1" />);
    expect(screen.queryByTestId('document-prerequisites')).not.toBeInTheDocument();
  });

  it('renders above the Entities list, one line per blocked document, with Add for the missing master', () => {
    detailBox.current = detail(
      {
        sourceKind: 'db',
        documentPrerequisites: [
          { entityType: 'sales_order', missing: [], inactive: ['product'] },
          { entityType: 'purchase_order', missing: ['supplier'], inactive: ['product'] },
        ],
      },
      [entity('customer'), entity('product'), entity('sales_order'), entity('purchase_order')],
    );
    render(<AutocountCompanyDetailView companyId="c1" />);
    const card = screen.getByTestId('document-prerequisites');
    expect(card).toHaveTextContent('Sales Orders will stay retryable until Products is active.');
    expect(card).toHaveTextContent('Purchase Orders will stay retryable until Suppliers and Products are active.');
    // Above the list: the card precedes the entities list in document order
    // (the Runs tab renders its own list - scope to the Entities tab).
    const list = within(screen.getByTestId('tab-entities')).getByTestId('entities-list');
    expect(card.compareDocumentPosition(list) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    // "Add entity" affordance for the MISSING master opens its task editor.
    fireEvent.click(screen.getByTestId('add-prerequisite-supplier'));
    expect(push).toHaveBeenCalledWith('/autocount/companies/c1/entities/supplier');
  });

  it('also warns on an API company with a configured document entity (kind-agnostic)', () => {
    detailBox.current = detail(
      { sourceKind: 'api', documentPrerequisites: [{ entityType: 'sales_order', missing: ['customer'], inactive: [] }] },
      [entity('sales_order')],
    );
    render(<AutocountCompanyDetailView companyId="c1" />);
    expect(screen.getByTestId('document-prerequisites')).toHaveTextContent('Customers is active.');
  });
});
