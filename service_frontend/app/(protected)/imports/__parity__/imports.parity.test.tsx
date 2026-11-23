/**
 * Switch-off parity for the import dialog, the import page and the import
 * history list (Foundryx UIUX, slice W3-JOBS). Recorded on the code BEFORE the
 * slice changed anything, so a later change that alters what a user sees, or
 * what reaches the backend, with the switch off fails here. A change that
 * needs one of these snapshots updated is wrong by definition: fix the code,
 * never the snapshot.
 */
import { Suspense, type ReactElement } from 'react';
import { act, fireEvent, render as rtlRender, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { SettingsProvider } from '@/providers/settings-provider';
import { parityHtml as baseParityHtml } from '@/components/fx/__parity__/parity-utils';
import type { ImportConfig, ImportJob, ImportPreview } from '@/types/import';

/** React 19's `_r_N_` ids renamed in order, so test order cannot shift them. */
function parityHtml(root: Element): string {
  const seen = new Map<string, string>();
  return baseParityHtml(root)
    .replace(/_r_[0-9a-z]+_/g, (id) => {
      if (!seen.has(id)) seen.set(id, `_rid${seen.size}_`);
      return seen.get(id) as string;
    })
    .replace(/(animation|transition)-duration:\s*[0-9.]+m?s/g, '$1-duration: <t>');
}

const h = vi.hoisted(() => ({
  calls: [] as unknown[],
  /** What `importService.get` answers next (a queue; the last one repeats). */
  gets: [] as unknown[],
}));

vi.mock('@/lib/toast', () => {
  const t = (kind: string) => (...args: unknown[]) => {
    h.calls.push([`toast.${kind}`, ...args]);
    return 'toast-id';
  };
  return {
    toast: {
      success: t('success'),
      error: t('error'),
      info: t('info'),
      warning: t('warning'),
      message: t('message'),
      custom: t('custom'),
      dismiss: t('dismiss'),
      fxDone: t('fxDone'),
    },
  };
});

vi.mock('next/navigation', () => ({
  useRouter: () => ({
    push: (...args: unknown[]) => h.calls.push(['router.push', ...args]),
    replace: vi.fn(),
    prefetch: vi.fn(),
    back: vi.fn(),
    refresh: vi.fn(),
  }),
  usePathname: () => '/user-management/users',
  useSearchParams: () => new URLSearchParams('from=%2Fuser-management%2Fusers'),
  useParams: () => ({}),
}));

vi.mock('next-auth/react', () => ({
  useSession: () => ({
    data: { user: { name: 'Kay Tan', timezone: 'Asia/Kuala_Lumpur', permissions: [] } },
    status: 'authenticated',
  }),
}));

vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({ can: () => true, ready: true, permissions: new Set<string>() }),
}));
vi.mock('@/hooks/use-terminology', () => ({
  useTerminology: () => ({
    ready: true,
    label: (k: string) => k,
    labelPlural: (k: string) => k,
    t: (k: string) => k,
    refetch: vi.fn(),
  }),
}));
vi.mock('@/lib/impersonation-store', () => ({ useImpersonationSession: () => null }));
vi.mock('@/services/preferences-service', () => ({
  preferencesService: { get: vi.fn().mockResolvedValue(null), save: vi.fn().mockResolvedValue(undefined) },
}));
vi.mock('@/services/terminology-service', () => ({
  terminologyService: { getTerminology: vi.fn().mockResolvedValue({}) },
}));
vi.mock('@/providers/import-activity-provider', () => ({
  useImportActivity: () => ({
    openImport: vi.fn(),
    refresh: async () => {
      h.calls.push(['imports.refresh']);
    },
  }),
}));

export const CONFIG: ImportConfig = {
  entityType: 'user',
  label: 'Users',
  columns: [
    { key: 'name', label: 'Name', type: 'string', required: true, unique: false, options: null, hasResolver: false },
    { key: 'email', label: 'Email', type: 'email', required: true, unique: true, options: null, hasResolver: false },
    { key: 'phone', label: 'Phone', type: 'string', required: false, unique: false, options: null, hasResolver: false },
    { key: 'id', label: 'ID', type: 'string', required: false, unique: true, options: null, hasResolver: false },
  ],
  modes: ['create_only', 'update_only', 'upsert'],
  contextKeys: [],
};

export const PREVIEW: ImportPreview = {
  sheets: ['Sheet1'],
  sheetName: 'Sheet1',
  headers: ['Full name', 'E-mail', 'Mobile', 'Notes'],
  autoMapping: { 'Full name': 'name', 'E-mail': 'email', Mobile: 'phone', Notes: null },
};

export function importJob(over: Partial<ImportJob> = {}): ImportJob {
  return {
    id: 'imp-1',
    entityType: 'user',
    mode: 'create_only',
    status: 'pending',
    abortOnInvalid: false,
    triggerAutomations: false,
    sheetName: 'Sheet1',
    mapping: null,
    context: null,
    totalRows: 0,
    validRows: 0,
    invalidRows: 0,
    errors: null,
    hasErrorFile: false,
    createdIds: null,
    updatedIds: null,
    filesPurged: false,
    createdAt: '2026-11-18T02:00:00Z',
    finishedAt: null,
    ...over,
  };
}

const VALIDATED = importJob({
  status: 'validated',
  totalRows: 12,
  validRows: 10,
  invalidRows: 2,
  errors: [
    { row: 4, column: 'email', message: 'Not an email address' },
    { row: 9, column: 'name', message: 'Required' },
  ],
  hasErrorFile: true,
});

const DONE = importJob({
  status: 'done',
  totalRows: 12,
  validRows: 10,
  invalidRows: 2,
  createdIds: ['u1', 'u2', 'u3', 'u4', 'u5', 'u6', 'u7', 'u8'],
  updatedIds: ['u9', 'u10'],
  finishedAt: '2026-11-18T02:05:00Z',
});

const HISTORY: ImportJob[] = [
  DONE,
  importJob({ id: 'imp-2', entityType: 'product', status: 'failed', totalRows: 5, validRows: 0, invalidRows: 5 }),
  importJob({ id: 'imp-3', entityType: 'contact', status: 'validated', mode: 'upsert', totalRows: 40, validRows: 38 }),
];

vi.mock('@/services/import-service', () => ({
  importService: {
    getConfig: (...args: unknown[]) => {
      h.calls.push(['import.getConfig', ...args]);
      return Promise.resolve(CONFIG);
    },
    create: (input: { file: File } & Record<string, unknown>) => {
      h.calls.push(['import.create', { ...input, file: input.file.name }]);
      return Promise.resolve({ jobId: 'imp-1' });
    },
    preview: (...args: unknown[]) => {
      h.calls.push(['import.preview', ...args]);
      return Promise.resolve(PREVIEW);
    },
    get: (...args: unknown[]) => {
      h.calls.push(['import.get', ...args]);
      const next = h.gets.length > 1 ? h.gets.shift() : h.gets[0];
      return Promise.resolve(next);
    },
    setMapping: (...args: unknown[]) => {
      h.calls.push(['import.setMapping', ...args]);
      return Promise.resolve(VALIDATED);
    },
    commit: (...args: unknown[]) => {
      h.calls.push(['import.commit', ...args]);
      return Promise.resolve(importJob({ status: 'importing' }));
    },
    list: (...args: unknown[]) => {
      h.calls.push(['import.list', ...args]);
      return Promise.resolve({ items: HISTORY, total: HISTORY.length, page: 0, pageSize: 50 });
    },
    downloadErrorFile: (...args: unknown[]) => {
      h.calls.push(['import.downloadErrorFile', ...args]);
      return Promise.resolve(new Blob(['row,problem']));
    },
    downloadTemplate: (...args: unknown[]) => {
      h.calls.push(['import.downloadTemplate', ...args]);
      return Promise.resolve(new Blob(['name,email']));
    },
  },
}));

// Imported after the mocks.
import { ImportModal } from '@/components/platform/import-wizard/import-modal';
import ImportPage from '../[jobId]/page';
import ImportsHistoryPage from '../page';

function render(ui: ReactElement) {
  return rtlRender(<SettingsProvider>{ui}</SettingsProvider>);
}

async function settle(ms = 50) {
  await act(async () => {
    await new Promise((r) => setTimeout(r, ms));
  });
}

function calls(): unknown[] {
  return JSON.parse(JSON.stringify(h.calls));
}

beforeEach(() => {
  h.calls.length = 0;
  h.gets = [importJob()];
  URL.createObjectURL = vi.fn(() => 'blob:x');
  URL.revokeObjectURL = vi.fn();
});

describe('switch-off parity: import dialog', () => {
  it('renders as today and uploads the same request', async () => {
    render(<ImportModal entityType="user" onClose={() => h.calls.push(['onClose'])} />);
    await screen.findByText('Import Users');
    await settle();
    expect(parityHtml(document.body)).toMatchSnapshot();

    const input = document.body.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(['Full name,E-mail\nAisyah,a@x.my'], 'users.csv', { type: 'text/csv' });
    fireEvent.change(input, { target: { files: [file] } });
    fireEvent.click(screen.getByRole('button', { name: 'Upload & map' }));
    await settle();
    expect(calls()).toMatchSnapshot();
  });

  it('downloads the template with the same request', async () => {
    render(<ImportModal entityType="user" onClose={() => {}} />);
    await screen.findByText('Import Users');
    fireEvent.click(screen.getByRole('button', { name: /Download template/ }));
    await screen.findByText('Choose the format and which columns to include.');
    await settle();
    expect(parityHtml(document.body)).toMatchSnapshot();
    fireEvent.click(screen.getByRole('button', { name: 'Download .xlsx' }));
    await settle();
    expect(calls()).toMatchSnapshot();
  });
});

async function renderImportPage() {
  const params = Promise.resolve({ jobId: 'imp-1' });
  let view!: ReturnType<typeof render>;
  await act(async () => {
    view = render(
      <Suspense fallback={null}>
        <ImportPage params={params} />
      </Suspense>,
    );
  });
  await screen.findByText('Map columns');
  await settle();
  return view;
}

describe('switch-off parity: import page', () => {
  it('renders the mapping as today', async () => {
    const { container } = await renderImportPage();
    expect(parityHtml(container)).toMatchSnapshot();
    expect(calls()).toMatchSnapshot();
  });

  it('Test sends the same requests and shows the results as today', async () => {
    const { container } = await renderImportPage();
    h.calls.length = 0;
    h.gets = [VALIDATED];
    fireEvent.click(screen.getByRole('button', { name: 'Test' }));
    await settle();
    expect(calls()).toMatchSnapshot();
    expect(parityHtml(container)).toMatchSnapshot();
  });

  it('Import straight away validates, commits and goes back as today', async () => {
    await renderImportPage();
    h.calls.length = 0;
    h.gets = [VALIDATED, DONE];
    fireEvent.click(screen.getByText('Abort the whole import if any row is invalid'));
    fireEvent.click(screen.getByText('Trigger automations for imported rows'));
    fireEvent.click(screen.getByRole('button', { name: 'Import' }));
    await settle();
    expect(calls()).toMatchSnapshot();
  });

  it('Error file downloads the same file as today', async () => {
    await renderImportPage();
    h.gets = [VALIDATED];
    fireEvent.click(screen.getByRole('button', { name: 'Test' }));
    await settle();
    h.calls.length = 0;
    fireEvent.click(screen.getByRole('button', { name: /Error file/ }));
    await settle();
    expect(calls()).toMatchSnapshot();
  });
});

describe('switch-off parity: import history', () => {
  it('renders the list as today', async () => {
    const { container } = render(<ImportsHistoryPage />);
    await screen.findByText('product');
    await settle();
    expect(parityHtml(container)).toMatchSnapshot();
    expect(calls()).toMatchSnapshot();
  });
});
