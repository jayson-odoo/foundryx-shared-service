/**
 * The AutoCount review, pull and find pages with the Foundryx UIUX switch on
 * (slice W5-AC-OPS).
 *
 * - Every write the pages make (preview push, approve, discard of a batch;
 *   issue key and build snapshot; the find query) is sent exactly as with the
 *   switch off: requests are captured at `apiFetch` under the real services
 *   (same path, method and body), in both looks, from the same input.
 * - Approve is the page's red action and keeps today's gate (blocked until the
 *   dry run was previewed, and while it fails); Discard keeps its confirm.
 * - Find: Enter in the number field submits the same query as the button did.
 * - Amounts keep today's numbers (two decimals) and gain the currency before
 *   them: "RM" for MYR, the ISO code otherwise; negative, zero and large too.
 *
 * Nothing here reaches a real AutoCount server: every call is stubbed at
 * `apiFetch`. Switch off is pinned by `__parity__/ops.parity.test.tsx`.
 */
import type { ReactNode } from 'react';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { FX_DEFAULT_THEME } from '@/lib/fx/cookies';
import { FxProvider } from '@/providers/fx-provider';
import { SettingsProvider } from '@/providers/settings-provider';
import { resetPageActionsForTests } from '@/components/fx/actions/page-actions-context';
import { realAutocountDocLookupService } from '@/services/autocount-doc-lookup-service.real';
import { formatMoneyFx } from '@/lib/money';
import type { AutocountCompany } from '@/types/autocount';
import type { DocLookupResult, DocLookupStored } from '@/types/autocount-doc-lookup';
import { ReviewView } from './review/[jobId]/components/review-view';
import { IssueKeyDialog } from './pull/components/issue-key-dialog';
import { BuildSnapshotDialog } from './pull/components/build-snapshot-dialog';
import { FindDocumentView } from './find/components/find-document-view';
import { DocResult } from './find/components/doc-result';
import { useAutocountPullListConfig } from './pull/components/use-pull-list-config';
import { useAutocountJobsListConfig } from './review/components/use-jobs-list-config';
import { renderHook } from '@testing-library/react';

const net = vi.hoisted(() => ({ apiFetch: vi.fn(), apiFetchText: vi.fn() }));
vi.mock('@/lib/api-client', async (orig) => {
  const real = (await orig()) as Record<string, unknown>;
  return { ...real, apiFetch: net.apiFetch, apiFetchText: net.apiFetchText };
});

const toasts = vi.hoisted(() => ({
  fxDone: vi.fn(),
  error: vi.fn(),
  success: vi.fn(),
  warning: vi.fn(),
}));
vi.mock('@/lib/toast', async (orig) => {
  const real = (await orig()) as { toast: Record<string, unknown> };
  return { toast: { ...real.toast, ...toasts } };
});

const push = vi.fn();
vi.mock('next/navigation', () => ({
  useRouter: vi.fn(() => ({ push, prefetch: vi.fn(), replace: vi.fn(), back: vi.fn() })),
  useSearchParams: vi.fn(() => new URLSearchParams()),
  usePathname: vi.fn(() => '/autocount/review/job-1'),
  useParams: vi.fn(() => ({})),
}));
vi.mock('next-themes', () => ({ useTheme: () => ({ theme: 'light', setTheme: vi.fn() }) }));
vi.mock('next-auth/react', () => ({
  useSession: () => ({
    data: { user: { name: 'Nurul Huda', permissions: [] } },
    status: 'authenticated',
    update: vi.fn(),
  }),
}));
vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({ can: () => true, ready: true, permissions: new Set<string>() }),
}));
vi.mock('@/lib/impersonation-store', () => ({ useImpersonationSession: () => null }));
vi.mock('@/services/preferences-service', () => ({
  preferencesService: { get: vi.fn().mockResolvedValue(null), save: vi.fn().mockResolvedValue(undefined) },
}));
vi.mock('@/services/terminology-service', () => ({
  terminologyService: { getTerminology: vi.fn().mockResolvedValue({}) },
}));
vi.mock('@/providers/import-activity-provider', () => ({
  useImportActivity: () => ({ openImport: vi.fn() }),
}));
vi.mock('@/services/pending-actions-service', () => ({
  pendingActionsService: { park: vi.fn(), cancel: vi.fn(), current: vi.fn().mockResolvedValue({ pending: null }) },
}));
// The staged records have their own list and are not under test here.
vi.mock('./review/[jobId]/components/staged-records-list', () => ({
  StagedRecordsList: () => <div data-stub="staged" />,
}));
// A popover list inside a dialog is not under test: a plain toggle list.
vi.mock('@/components/platform/multi-select', () => ({
  MultiSelect: ({
    options,
    value,
    onChange,
  }: {
    options: { label: string; value: string }[];
    value: string[];
    onChange: (v: string[]) => void;
  }) => (
    <div>
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          onClick={() => onChange(value.includes(o.value) ? value.filter((x) => x !== o.value) : [...value, o.value])}
        >
          {`toggle ${o.label}`}
        </button>
      ))}
    </div>
  ),
}));

const COMPANY: AutocountCompany = {
  id: 'c1',
  connectionId: 'conn-1',
  databaseName: 'AED_VSOFT',
  companyName: 'V Soft Trading',
  name: 'V Soft',
  isActive: true,
  sinkImpl: 'sorento',
  sinkConnectionId: 'sink-1',
  sorentoCompanyCode: 'VSOFT',
  createdAt: '2026-11-02T03:00:00Z',
  sourceKind: 'db',
  documentPrerequisites: [],
};

let jobStatus = 'needs_review';
let previewFails = false;

const FOUND_NOT: DocLookupResult = {
  found: false,
  docNo: 'PS202610-0004',
  docType: 'delivery_order',
  current: null,
  redated: null,
  foundBy: null,
  steps: [],
  searched: {
    lastModifiedFrom: null,
    lastModifiedTo: null,
    docDateFrom: '2026-10-01',
    docDateTo: '2026-10-31',
  },
} as unknown as DocLookupResult;

function route(path: string, init?: RequestInit): unknown {
  const method = init?.method ?? 'GET';
  if (method === 'GET') {
    if (path.startsWith('/autocount/jobs/job-1/staged')) {
      return {
        data: [],
        total: 14,
        page: 0,
        noChangeCount: 4,
        job: {
          id: 'job-1',
          status: jobStatus,
          progressTotal: 14,
          progressDone: 14,
          progressFailed: 0,
          result: null,
          error: null,
          createdAt: '2026-11-10T04:00:00Z',
        },
      };
    }
    if (path.startsWith('/autocount/companies?')) return { data: [COMPANY], total: 1, page: 0 };
    if (path === '/autocount/companies/c1') {
      return {
        company: COMPANY,
        entities: [
          { id: 'product', entityType: 'product', deliveryMode: 'pull', etlStatus: 'active', enabled: true },
        ],
      };
    }
    if (path.startsWith('/autocount/doc-lookup/types')) {
      return {
        data: [
          { key: 'delivery_order', label: 'Delivery order', prefixes: ['PS'], hasLastModified: true, hasByDocNo: false, connected: true },
        ],
      };
    }
    if (path.startsWith('/autocount/doc-lookup/stored')) {
      return { snapshots: [], ledger: null } satisfies DocLookupStored;
    }
    return [];
  }
  if (path.endsWith('/preview')) {
    if (previewFails) throw new Error('unreachable');
    return {
      preview: {
        previewable: true,
        sink: 'sorento',
        summary: { total: 14, created: 9, updated: 3, failed: 2, retryable: 1 },
        predictions: [],
      },
    };
  }
  if (path.endsWith('/approve') || path.endsWith('/discard')) return { jobId: 'job-1', status: 'done' };
  if (path === '/autocount/pull/keys') {
    return {
      id: 'k1',
      name: JSON.parse(String(init?.body)).name,
      keyPrefix: 'fxa_live_ab',
      companyIds: ['c1'],
      createdAt: '2026-11-10T04:00:00Z',
      lastUsedAt: null,
      revokedAt: null,
      plaintext: 'fxa_live_abcdef0123456789',
    };
  }
  if (path === '/autocount/pull/snapshots') {
    return { id: 'snap-9', status: 'building', companyId: 'c1', entityType: 'product' };
  }
  if (path === '/autocount/doc-lookup') {
    return { jobId: 'lk1', status: 'done', error: null, result: FOUND_NOT };
  }
  return {};
}

function look(on: boolean) {
  return function Look({ children }: { children: ReactNode }) {
    return (
      <FxProvider initial={on} initialTheme={FX_DEFAULT_THEME}>
        <SettingsProvider>{children}</SettingsProvider>
      </FxProvider>
    );
  };
}

/** Every write sent: path, method and body, in order. */
function writes() {
  return net.apiFetch.mock.calls
    .filter(([, init]) => init && (init as RequestInit).method && (init as RequestInit).method !== 'GET')
    .map(([path, init]) => ({
      path,
      method: (init as RequestInit).method,
      body: (init as RequestInit).body ?? null,
    }));
}

beforeEach(() => {
  push.mockReset();
  net.apiFetch.mockReset();
  net.apiFetch.mockImplementation(async (path: string, init?: RequestInit) => route(path, init));
  Object.values(toasts).forEach((fn) => fn.mockReset());
  jobStatus = 'needs_review';
  previewFails = false;
  window.localStorage.clear();
  window.sessionStorage.clear();
});
afterEach(() => resetPageActionsForTests());

describe('Batch review: the same requests in both looks', () => {
  async function approveFlow(on: boolean) {
    const user = userEvent.setup();
    render(<ReviewView jobId="job-1" />, { wrapper: look(on) });
    await screen.findByTestId('preview-push');
    await user.click(screen.getByTestId('preview-push'));
    await screen.findByText('Dry-run preview');
    await user.click(
      on
        ? await screen.findByRole('button', { name: /Approve/ })
        : screen.getByTestId('approve-batch'),
    );
    await waitFor(() => expect(writes()).toHaveLength(2));
  }

  it('preview, then approve', async () => {
    await approveFlow(false);
    const off = writes();
    expect(off).toEqual([
      { path: '/autocount/jobs/job-1/preview', method: 'POST', body: null },
      { path: '/autocount/jobs/job-1/approve', method: 'POST', body: null },
    ]);
    expect(toasts.success).toHaveBeenCalledWith('Batch approved.');
    expect(toasts.fxDone).not.toHaveBeenCalled();
    cleanup();
    net.apiFetch.mockClear();
    await approveFlow(true);
    expect(writes()).toEqual(off);
    await waitFor(() =>
      expect(toasts.fxDone).toHaveBeenCalledWith({
        what: 'Batch approved for push',
        howMany: '14 records',
        byWhom: 'Nurul Huda',
      }),
    );
    expect(toasts.fxDone.mock.calls[0][0].undo).toBeUndefined();
  });

  async function discardFlow(on: boolean) {
    const user = userEvent.setup();
    render(<ReviewView jobId="job-1" />, { wrapper: look(on) });
    await screen.findByTestId('preview-push');
    await user.click(
      on ? await screen.findByRole('button', { name: 'Discard batch' }) : screen.getByTestId('discard-batch'),
    );
    // The confirm is still there: nothing was sent yet.
    expect(writes()).toHaveLength(0);
    const dialog = await screen.findByRole('alertdialog');
    await user.click(within(dialog).getByRole('button', { name: on ? 'Discard batch' : 'Discard' }));
    await waitFor(() => expect(writes()).toHaveLength(1));
  }

  it('discard asks first, then sends the same request', async () => {
    await discardFlow(false);
    const off = writes();
    expect(off).toEqual([{ path: '/autocount/jobs/job-1/discard', method: 'POST', body: null }]);
    expect(toasts.success).toHaveBeenCalledWith('Batch discarded - nothing was pushed.');
    cleanup();
    net.apiFetch.mockClear();
    await discardFlow(true);
    expect(writes()).toEqual(off);
    await waitFor(() =>
      expect(toasts.fxDone).toHaveBeenCalledWith({
        what: 'Batch discarded',
        howMany: 'nothing pushed',
        byWhom: 'Nurul Huda',
      }),
    );
  });

  it('on: Approve is blocked, with the reason, until the dry run was previewed', async () => {
    const user = userEvent.setup();
    render(<ReviewView jobId="job-1" />, { wrapper: look(true) });
    const approve = await screen.findByRole('button', { name: /Approve/ });
    expect(approve).toHaveAttribute('aria-disabled', 'true');
    await user.click(approve);
    expect(writes()).toHaveLength(0);
    expect(screen.getByText('Preview the push first.')).toBeInTheDocument();
  });

  it('on: a failing dry run keeps Approve blocked', async () => {
    previewFails = true;
    const user = userEvent.setup();
    render(<ReviewView jobId="job-1" />, { wrapper: look(true) });
    await user.click(await screen.findByTestId('preview-push'));
    await screen.findByText('Resolve the dry run first.');
    await user.click(screen.getByRole('button', { name: /Approve/ }));
    expect(writes().map((w) => w.path)).toEqual(['/autocount/jobs/job-1/preview']);
  });

  it('on: a batch that was already reviewed cannot be approved or discarded', async () => {
    jobStatus = 'done';
    render(<ReviewView jobId="job-1" />, { wrapper: look(true) });
    expect(await screen.findAllByText('This batch has already been reviewed.')).not.toHaveLength(0);
    await userEvent.setup().click(screen.getByRole('button', { name: /Approve/ }));
    expect(writes()).toHaveLength(0);
  });
});

describe('Pull: the same requests in both looks', () => {
  async function issue(on: boolean) {
    const user = userEvent.setup();
    render(<IssueKeyDialog open onOpenChange={vi.fn()} companies={[COMPANY]} onIssued={vi.fn()} />, {
      wrapper: look(on),
    });
    await user.type(screen.getByLabelText('Name'), 'Night job');
    await user.click(screen.getByText('toggle V Soft'));
    await user.click(screen.getByRole('button', { name: 'Issue key' }));
    await screen.findByLabelText('Plaintext key');
  }

  it('issue key sends the same body and shows the key once', async () => {
    await issue(false);
    const off = writes();
    expect(off).toEqual([
      {
        path: '/autocount/pull/keys',
        method: 'POST',
        body: JSON.stringify({ name: 'Night job', companyIds: ['c1'] }),
      },
    ]);
    cleanup();
    net.apiFetch.mockClear();
    await issue(true);
    expect(writes()).toEqual(off);
    expect((screen.getByLabelText('Plaintext key') as HTMLInputElement).value).toBe('fxa_live_abcdef0123456789');
    expect(screen.getByText(/won't be shown again/)).toBeInTheDocument();
  });

  async function build(on: boolean) {
    const user = userEvent.setup();
    render(<BuildSnapshotDialog open onOpenChange={vi.fn()} companies={[COMPANY]} onBuilt={vi.fn()} />, {
      wrapper: look(on),
    });
    await user.click(screen.getByRole('combobox', { name: 'Company' }));
    await user.click(await screen.findByRole('option', { name: 'V Soft' }));
    await user.click(screen.getByRole('combobox', { name: 'Entity' }));
    await user.click(await screen.findByRole('option', { name: /Product/ }));
    await user.click(screen.getByRole('button', { name: 'Build' }));
    await waitFor(() => expect(writes()).toHaveLength(1));
  }

  it('build snapshot sends the same body', async () => {
    await build(false);
    const off = writes();
    expect(off).toEqual([
      {
        path: '/autocount/pull/snapshots',
        method: 'POST',
        body: JSON.stringify({ companyId: 'c1', entityType: 'product' }),
      },
    ]);
    cleanup();
    net.apiFetch.mockClear();
    push.mockReset();
    await build(true);
    expect(writes()).toEqual(off);
    expect(push).toHaveBeenCalledWith('/autocount/pull/snapshots/snap-9');
  });

  it('revoke stays the same grace-window action; the list only gains words', () => {
    const { result } = renderHook(
      () => useAutocountPullListConfig({ companies: [COMPANY], onIssueKey: vi.fn(), onBuildSnapshot: vi.fn() }),
      { wrapper: look(true) },
    );
    const revoke = result.current.actions.find((a) => a.id === 'revoke')!;
    expect(revoke.deferred).toMatchObject({
      actionKey: 'autocount_pull_api_key.revoke',
      entityType: 'autocount_pull_api_key',
    });
    expect(revoke.confirm).toBeUndefined();
    const fxName = (revoke.deferred as { fxName: (rows: unknown[]) => string | undefined }).fxName;
    expect(fxName([{ kind: 'key', name: 'Night job' }])).toBe('Night job');
    expect(result.current.fx?.columnKind).toEqual({ status: 'status' });
  });

  it('the review list declares its status column and right-aligns the counts', () => {
    const { result } = renderHook(() => useAutocountJobsListConfig(), { wrapper: look(true) });
    expect(result.current.fx?.columnKind).toEqual({ status: 'status' });
    expect(result.current.columns.find((c) => c.id === 'records')?.meta).toMatchObject({ fxAlign: 'end' });
  });
});

describe('Find document: the same query in both looks', () => {
  async function find(on: boolean, submit: 'button' | 'enter') {
    const user = userEvent.setup();
    render(<FindDocumentView lookupOptions={{ service: realAutocountDocLookupService }} />, {
      wrapper: look(on),
    });
    await user.click(await screen.findByRole('combobox', { name: 'Company' }));
    await user.click(await screen.findByRole('option', { name: 'V Soft' }));
    await user.type(screen.getByLabelText('Document number *'), '  PS202610-0004 ');
    // The type follows once the company's types have loaded.
    await waitFor(() => {
      const btn = screen.getByRole('button', { name: /Find/ });
      expect(btn).not.toBeDisabled();
      expect(btn).not.toHaveAttribute('aria-disabled', 'true');
    });
    if (submit === 'button') {
      await user.click(screen.getByRole('button', { name: /Find/ }));
    } else {
      await user.keyboard('{Enter}');
    }
    await waitFor(() => expect(writes(), JSON.stringify(net.apiFetch.mock.calls.map((c) => c[0]))).toHaveLength(1));
  }

  it('the typed text sends the same request, by button (off) and by Enter (both)', async () => {
    await find(false, 'button');
    const off = writes();
    expect(off).toEqual([
      {
        path: '/autocount/doc-lookup',
        method: 'POST',
        body: JSON.stringify({
          companyId: 'c1',
          docNo: 'PS202610-0004',
          docType: 'delivery_order',
          aroundDay: null,
        }),
      },
    ]);
    cleanup();
    net.apiFetch.mockClear();
    await find(false, 'enter');
    expect(writes()).toEqual(off);
    cleanup();
    net.apiFetch.mockClear();
    await find(true, 'enter');
    expect(writes()).toEqual(off);
    cleanup();
    net.apiFetch.mockClear();
    await find(true, 'button');
    expect(writes()).toEqual(off);
  });

  it('on: Find is the red action, blocked with its reason until a company and a number are given', async () => {
    const user = userEvent.setup();
    render(<FindDocumentView lookupOptions={{ service: realAutocountDocLookupService }} />, {
      wrapper: look(true),
    });
    const findBtn = await screen.findByRole('button', { name: /Find/ });
    expect(screen.getByText('Pick a company.')).toBeInTheDocument();
    await user.click(findBtn);
    expect(writes()).toHaveLength(0);
    await user.type(screen.getByLabelText('Document number *'), '{Enter}');
    expect(writes()).toHaveLength(0);
  });
});

describe('Find document: amounts keep their numbers', () => {
  const lookup = (netTotal: unknown, currency: string | null, subTotals: number[]) =>
    ({
      found: true,
      docNo: 'INV-1',
      docType: 'invoice',
      redated: null,
      foundBy: null,
      steps: [],
      searched: {},
      current: {
        docNo: 'INV-1',
        docKey: 1,
        docDate: '2026-10-05',
        cancelled: false,
        lastModified: '2026-10-05T00:00:00',
        lastModifiedBy: null,
        header: { NetTotal: netTotal, ...(currency ? { CurrencyCode: currency } : {}) },
        lines: subTotals.map((n, i) => ({ Seq: i + 1, SubTotal: n })),
      },
    }) as unknown as DocLookupResult;

  it.each([
    ['MYR', 1250, 'MYR 1,250.00', 'RM 1,250.00'],
    ['MYR', -12.5, 'MYR -12.50', '-RM 12.50'],
    ['MYR', 0, 'MYR 0.00', 'RM 0.00'],
    ['SGD', 14000, 'SGD 14,000.00', 'SGD 14,000.00'],
    ['MYR', 12345678.9, 'MYR 12,345,678.90', 'RM 12,345,678.90'],
    ['JPY', 1000.5, 'JPY 1,000.50', 'JPY 1,000.50'],
  ])('%s %s: off "%s", on "%s"', (currency, amount, offText, onText) => {
    const result = lookup(amount, currency, [amount]);
    const { unmount } = render(<DocResult result={result} stored={null} typeLabel="Invoice" />, { wrapper: look(false) });
    expect(screen.getAllByText(offText).length).toBeGreaterThan(0);
    unmount();
    render(<DocResult result={result} stored={null} typeLabel="Invoice" />, { wrapper: look(true) });
    expect(screen.getAllByText(onText).length).toBeGreaterThan(0);
    expect(screen.getByTestId('ac-find-lines-total')).toHaveTextContent(onText);
  });

  it('a number with no currency stays a plain number in both looks', () => {
    const result = lookup(980.5, null, [980.5]);
    const { unmount } = render(<DocResult result={result} stored={null} typeLabel="Invoice" />, { wrapper: look(false) });
    expect(screen.getByTestId('ac-find-lines-total')).toHaveTextContent('980.50');
    unmount();
    render(<DocResult result={result} stored={null} typeLabel="Invoice" />, { wrapper: look(true) });
    expect(screen.getByTestId('ac-find-lines-total')).toHaveTextContent('980.50');
  });

  it('the formatter itself', () => {
    expect(formatMoneyFx(-0.001, 'MYR', 2)).toBe('RM 0.00');
    expect(formatMoneyFx(1, 'usd', 2)).toBe('USD 1.00');
  });
});
