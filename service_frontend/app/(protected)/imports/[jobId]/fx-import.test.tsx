/**
 * The import wizard under the Foundryx UIUX switch (slice W3-JOBS): the same
 * file, columns and choices send the same requests with the switch on as with
 * it off; the one approved difference is that Import waits for a check of the
 * current columns ("Check always before Import").
 */
import { Suspense, type ReactNode } from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { FX_DEFAULT_THEME } from '@/lib/fx/cookies';
import { FxProvider } from '@/providers/fx-provider';
import { TooltipsProvider } from '@/providers/tooltips-provider';
import { SettingsProvider } from '@/providers/settings-provider';
import { resetPageActionsForTests } from '@/components/fx/actions/page-actions-context';
import type { ImportConfig, ImportJob, ImportPreview } from '@/types/import';

const h = vi.hoisted(() => ({
  calls: [] as unknown[],
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
vi.mock('@/providers/import-activity-provider', () => ({
  useImportActivity: () => ({
    openImport: vi.fn(),
    refresh: async () => {
      h.calls.push(['imports.refresh']);
    },
  }),
}));

const CONFIG: ImportConfig = {
  entityType: 'user',
  label: 'User',
  columns: [
    { key: 'name', label: 'Name', type: 'string', required: true, unique: false, options: null, hasResolver: false },
    { key: 'email', label: 'Email', type: 'email', required: true, unique: true, options: null, hasResolver: false },
    { key: 'phone', label: 'Phone', type: 'string', required: false, unique: false, options: null, hasResolver: false },
  ],
  modes: ['create_only', 'update_only', 'upsert'],
  contextKeys: [],
};
const PREVIEW: ImportPreview = {
  sheets: ['Sheet1'],
  sheetName: 'Sheet1',
  headers: ['Full name', 'E-mail', 'Mobile', 'Notes'],
  autoMapping: { 'Full name': 'name', 'E-mail': 'email', Mobile: 'phone', Notes: null },
};
function importJob(over: Partial<ImportJob> = {}): ImportJob {
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
  errors: [{ row: 4, column: 'email', message: 'Not an email address' }],
  hasErrorFile: true,
});
const DONE = importJob({ status: 'done', totalRows: 12, validRows: 10, invalidRows: 2, createdIds: ['a'] });

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
      return Promise.resolve(h.gets.length > 1 ? h.gets.shift() : h.gets[0]);
    },
    setMapping: (...args: unknown[]) => {
      h.calls.push(['import.setMapping', ...args]);
      return Promise.resolve(VALIDATED);
    },
    commit: (...args: unknown[]) => {
      h.calls.push(['import.commit', ...args]);
      return Promise.resolve(importJob({ status: 'importing' }));
    },
    downloadErrorFile: (...args: unknown[]) => {
      h.calls.push(['import.downloadErrorFile', ...args]);
      return Promise.resolve(new Blob(['x']));
    },
    downloadTemplate: (...args: unknown[]) => {
      h.calls.push(['import.downloadTemplate', ...args]);
      return Promise.resolve(new Blob(['x']));
    },
    list: vi.fn(),
  },
}));

import { ImportModal } from '@/components/platform/import-wizard/import-modal';
import { checkSignature, importMainAction, pluralNoun } from './fx-import-page';
import ImportPage from './page';

function Wrap({ fx, children }: { fx: boolean; children: ReactNode }) {
  return (
    <FxProvider initial={fx} initialTheme={FX_DEFAULT_THEME}>
      <TooltipsProvider>
        <SettingsProvider>{children}</SettingsProvider>
      </TooltipsProvider>
    </FxProvider>
  );
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
  resetPageActionsForTests();
  URL.createObjectURL = vi.fn(() => 'blob:x');
  URL.revokeObjectURL = vi.fn();
});

const FILE = () => new File(['Full name,E-mail\nAisyah,a@x.my'], 'users.csv', { type: 'text/csv' });

async function uploadThroughDialog(fx: boolean): Promise<unknown[]> {
  h.calls.length = 0;
  const view = render(
    <Wrap fx={fx}>
      <ImportModal entityType="user" context={{ project_id: 'p-1' }} onClose={() => h.calls.push(['onClose'])} />
    </Wrap>,
  );
  await screen.findByText('Import User');
  await settle();
  const input = document.body.querySelector('input[type="file"]') as HTMLInputElement;
  fireEvent.change(input, { target: { files: [FILE()] } });
  fireEvent.click(screen.getByRole('button', { name: fx ? 'Next' : 'Upload & map' }));
  await settle();
  view.unmount();
  return calls();
}

describe('import dialog: same upload request in both looks', () => {
  it('sends the same create request, closes and opens the import page', async () => {
    const off = await uploadThroughDialog(false);
    const on = await uploadThroughDialog(true);
    expect(on).toEqual(off);
    expect(off.map((c) => (c as unknown[])[0])).toEqual([
      'import.getConfig',
      'import.create',
      'onClose',
      'router.push',
    ]);
  });

  it('shows the file step of four and keeps Next greyed until a file is chosen', async () => {
    render(
      <Wrap fx>
        <ImportModal entityType="user" onClose={() => {}} />
      </Wrap>,
    );
    await screen.findByText('Import User');
    await settle();
    expect(screen.getByText('Step 1 of 4')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Next' })).toBeDisabled();
    expect(screen.getByText('Choose a file.')).toBeInTheDocument();
  });

  it('downloads the same template', async () => {
    const run = async (fx: boolean) => {
      h.calls.length = 0;
      const view = render(
        <Wrap fx={fx}>
          <ImportModal entityType="user" onClose={() => {}} />
        </Wrap>,
      );
      await screen.findByText('Import User');
      await settle();
      fireEvent.click(screen.getByRole('button', { name: /Download (a )?template/ }));
      fireEvent.click(await screen.findByRole('button', { name: 'Download .xlsx' }));
      await settle();
      view.unmount();
      return calls();
    };
    const off = await run(false);
    const on = await run(true);
    expect(on).toEqual(off);
  });
});

async function renderPage(fx: boolean) {
  const params = Promise.resolve({ jobId: 'imp-1' });
  let view!: ReturnType<typeof render>;
  await act(async () => {
    view = render(
      <Wrap fx={fx}>
        <Suspense fallback={null}>
          <ImportPage params={params} />
        </Suspense>
      </Wrap>,
    );
  });
  if (fx) await screen.findByRole('heading', { name: 'Match the columns' });
  else await screen.findByText('Map columns');
  await settle();
  return view;
}

/** The red action in the fx page header, by its full label. */
function mainAction(name: RegExp): HTMLElement {
  return screen.getByRole('button', { name });
}

describe('import page: same requests in both looks', () => {
  it('loads with the same reads', async () => {
    h.calls.length = 0;
    const off = await renderPage(false);
    const offCalls = calls();
    off.unmount();
    h.calls.length = 0;
    await renderPage(true);
    expect(calls()).toEqual(offCalls);
  });

  it('Check sends exactly what Test sends', async () => {
    const off = await renderPage(false);
    h.calls.length = 0;
    h.gets = [VALIDATED];
    fireEvent.click(screen.getByRole('button', { name: 'Test' }));
    await settle();
    const offCalls = calls();
    off.unmount();

    resetPageActionsForTests();
    await renderPage(true);
    h.calls.length = 0;
    h.gets = [VALIDATED];
    fireEvent.click(mainAction(/Check the users/));
    await settle();
    expect(calls()).toEqual(offCalls);
    expect(screen.getByText('10 rows ready')).toBeInTheDocument();
    expect(screen.getByText('Not an email address')).toBeInTheDocument();
  });

  it('Import after a check sends exactly what Test then Import send today, and goes back', async () => {
    const run = async (fx: boolean) => {
      resetPageActionsForTests();
      h.gets = [importJob()];
      const view = await renderPage(fx);
      h.calls.length = 0;
      h.gets = [VALIDATED];
      fireEvent.click(fx ? mainAction(/Check the users/) : screen.getByRole('button', { name: 'Test' }));
      await settle();
      fireEvent.click(
        fx
          ? screen.getByRole('radio', { name: 'Stop if any row has a problem' })
          : screen.getByText('Abort the whole import if any row is invalid'),
      );
      fireEvent.click(screen.getByText('Trigger automations for imported rows'));
      h.gets = [VALIDATED, DONE];
      fireEvent.click(fx ? mainAction(/Import 10 users/) : screen.getByRole('button', { name: 'Import' }));
      await settle();
      const out = calls();
      view.unmount();
      return out;
    };
    const off = await run(false);
    const on = await run(true);
    expect(on).toEqual(off);
    const commit = off.find((c) => (c as unknown[])[0] === 'import.commit') as unknown[];
    expect(commit[2]).toEqual({ abortOnInvalid: true, triggerAutomations: true });
    expect(off[off.length - 1]).toEqual(['router.push', '/user-management/users']);
  });

  it('the rows-with-problems file is the same download', async () => {
    const run = async (fx: boolean) => {
      resetPageActionsForTests();
      h.gets = [importJob()];
      const view = await renderPage(fx);
      h.gets = [VALIDATED];
      fireEvent.click(fx ? mainAction(/Check the users/) : screen.getByRole('button', { name: 'Test' }));
      await settle();
      h.calls.length = 0;
      fireEvent.click(screen.getByRole('button', { name: fx ? /Download rows with problems/ : /Error file/ }));
      await settle();
      const out = calls();
      view.unmount();
      return out;
    };
    expect(await run(true)).toEqual(await run(false));
  });
});

describe('import page: Check always before Import (approved change)', () => {
  it('offers Check, not Import, until the current columns are checked', async () => {
    await renderPage(true);
    expect(mainAction(/Check the users/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^Import \d/ })).toBeNull();
    expect(screen.getByText('Step 2 of 4')).toBeInTheDocument();
  });

  it('a change to the columns after a check asks for a new check', () => {
    const base = { 'Full name': 'name', 'E-mail': 'email' };
    const sig = checkSignature(base, 'Sheet1', undefined);
    expect(checkSignature({ ...base }, 'Sheet1', undefined)).toBe(sig);
    expect(checkSignature({ ...base, 'E-mail': null }, 'Sheet1', undefined)).not.toBe(sig);
    expect(checkSignature(base, 'Sheet2', undefined)).not.toBe(sig);
    expect(checkSignature(base, 'Sheet1', { ticket_mode: 'comp' })).not.toBe(sig);
  });

  it('the red action follows the step', () => {
    const noop = () => {};
    const base = { noun: 'user', phase: 'idle' as const, ticketError: null, onCheck: noop, onImport: noop };
    expect(importMainAction({ ...base, checked: false, job: VALIDATED })?.id).toBe('check');
    const ready = importMainAction({ ...base, checked: true, job: VALIDATED });
    expect(ready?.id).toBe('import');
    expect(ready?.label).toBe('Import 10 users');
    expect(ready?.blocked).toBeUndefined();
    expect(
      importMainAction({ ...base, checked: true, job: { ...VALIDATED, validRows: 0 } })?.blocked?.reason,
    ).toBe('No rows are ready to import.');
    expect(
      importMainAction({ ...base, checked: true, job: VALIDATED, ticketError: 'Pick an offering to issue tickets.' })
        ?.blocked?.reason,
    ).toBe('Pick an offering to issue tickets.');
    expect(importMainAction({ ...base, checked: true, job: DONE })).toBeNull();
    expect(importMainAction({ ...base, checked: true, job: { ...VALIDATED, validRows: 1 } })?.label).toBe(
      'Import 1 user',
    );
    expect(pluralNoun('contacts', 3)).toBe('contacts');
    expect(pluralNoun('category', 3)).toBe('categories');
  });

  it('a finished import shows its outcome with no red action', async () => {
    h.gets = [DONE];
    await renderPage(true);
    expect(screen.queryByRole('button', { name: /Check the users|Import \d/ })).toBeNull();
    expect(screen.getByRole('button', { name: 'Back' })).toBeInTheDocument();
    expect(screen.getByText('1 added, 2 with problems')).toBeInTheDocument();
  });
});
