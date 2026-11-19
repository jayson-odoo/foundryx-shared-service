/**
 * Switch-off parity for the documents pages (Foundryx UIUX, slice W3-DOCS):
 * the drive, its trash, upload and share dialogs, shared links, document
 * types, document settings and the storage migration wizard. Recorded on the
 * code BEFORE the slice changed anything, so a later change that alters what
 * a user sees, or what reaches the backend, with the switch off fails here. A
 * change that needs one of these snapshots updated is wrong by definition:
 * fix the code, never the snapshot.
 */
import type { ReactElement } from 'react';
import { act, fireEvent, render as rtlRender, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SettingsProvider } from '@/providers/settings-provider';
import { parityHtml as baseParityHtml } from '@/components/fx/__parity__/parity-utils';
import { docCalls, docSearch, migration, recorded } from './doc-mocks';
import { share } from './fixtures';

/** React 19's `_r_N_` ids renamed in order, so test order cannot shift them. */
function parityHtml(root: Element): string {
  const seen = new Map<string, string>();
  return baseParityHtml(root)
    .replace(/_r_[0-9a-z]+_/g, (id) => {
      if (!seen.has(id)) seen.set(id, `_rid${seen.size}_`);
      return seen.get(id) as string;
    })
    .replace(/(animation|transition)-duration:\s*[0-9.]+m?s/g, '$1-duration: <t>')
    .replace(/Dnd(DescribedBy|LiveRegion)-\d+/g, 'Dnd$1-<n>');
}

const m = vi.hoisted(() => ({
  migration: null as unknown,
}));

vi.mock('@/services/document-service', async () => (await import('./doc-mocks')).documentServiceModule());
vi.mock('@/components/platform/document-drive/upload-manager', async () =>
  (await import('./doc-mocks')).uploadManagerModule(),
);
vi.mock('@/components/platform/document-drive/downloads-manager', async () =>
  (await import('./doc-mocks')).downloadsModule(),
);
vi.mock('next/navigation', async () => (await import('./doc-mocks')).navigationModule());
vi.mock('@/lib/toast', async () => (await import('./doc-mocks')).toastModule());

vi.mock('@/components/platform/resource-actions/deferred-toast', async () => {
  const { docCalls: calls } = await import('./doc-mocks');
  return {
    deferredToast: (input: Record<string, unknown>) => {
      calls.push(['deferredToast', { ...input, commitAt: '<t>', onCancel: typeof input.onCancel }]);
      return 'deferred-toast';
    },
    dismissDeferredToast: (...args: unknown[]) => calls.push(['dismissDeferredToast', ...args]),
  };
});
vi.mock('@/hooks/use-deferred-action', async () => {
  const { docCalls: calls } = await import('./doc-mocks');
  return {
    useDeferredAction: () => ({
      state: { status: 'idle' },
      dimEntityIds: [],
      start: async (...args: unknown[]) => {
        calls.push(['deferred.start', ...args]);
        return { commitAt: '2026-11-18T02:00:10Z', windowSeconds: 10, failedCount: 0, parkedEntityIds: ['shr-1'] };
      },
      cancel: async () => calls.push(['deferred.cancel']),
      reset: () => {},
    }),
  };
});
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
vi.mock('@/hooks/use-storage-migration', () => ({
  useStorageMigration: () => m.migration,
}));

// Imported after the mocks.
import DocumentsPage from '../page';
import DocumentSharesPage from '../shares/page';
import DocumentTypesPage from '../types/page';
import DocumentSettingsPage from '../settings/page';
import { ShareDialog } from '@/components/platform/document-drive/share-dialog';
import { StorageMigrationWizard } from '@/components/platform/storage-migration-wizard';

function render(ui: ReactElement) {
  return rtlRender(<SettingsProvider>{ui}</SettingsProvider>);
}

async function settle(ms = 50) {
  await act(async () => {
    await new Promise((r) => setTimeout(r, ms));
  });
}


beforeEach(() => {
  docCalls.length = 0;
  docSearch.value = '';
  m.migration = migration();
});

describe('switch-off parity: drive', () => {
  it('renders the drive root as today', async () => {
    const { container } = render(<DocumentsPage />);
    await screen.findAllByText('Quotations');
    await screen.findByText('logo.png');
    await settle();
    expect(parityHtml(container)).toMatchSnapshot();
    expect(recorded()).toMatchSnapshot();
  });

  it('renders the upload dialog as today and hands picked files to the upload queue', async () => {
    render(<DocumentsPage />);
    await screen.findByText('logo.png');
    fireEvent.click(screen.getByRole('button', { name: /Upload/ }));
    const dialog = await screen.findByRole('dialog');
    await settle();
    expect(parityHtml(dialog)).toMatchSnapshot();
    docCalls.length = 0;
    const input = dialog.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [new File(['a'], 'a.pdf'), new File(['b'], 'b.png')] } });
    expect(recorded()).toMatchSnapshot();
  });

  it('creates a folder with the same request as today', async () => {
    render(<DocumentsPage />);
    await screen.findByText('logo.png');
    fireEvent.click(screen.getByRole('button', { name: /New folder/ }));
    const input = await screen.findByLabelText('Folder name');
    fireEvent.change(input, { target: { value: '  Receipts  ' } });
    docCalls.length = 0;
    fireEvent.click(screen.getByRole('button', { name: 'Create folder' }));
    await settle();
    expect(recorded()).toMatchSnapshot();
  });

  async function menuOn(name: string, item: string) {
    const entry = document.querySelector(`[data-name="${name}"]`) as HTMLElement;
    fireEvent.contextMenu(entry, { clientX: 20, clientY: 20 });
    fireEvent.click(await screen.findByRole('menuitem', { name: item }));
  }

  it('renames a file with the same request as today', async () => {
    render(<DocumentsPage />);
    await screen.findByText('logo.png');
    await menuOn('invoice-2026-11.pdf', 'Rename');
    const input = await screen.findByLabelText('Name');
    fireEvent.change(input, { target: { value: 'invoice-nov.pdf ' } });
    docCalls.length = 0;
    fireEvent.click(screen.getByRole('button', { name: 'Rename file' }));
    await settle();
    expect(recorded()).toMatchSnapshot();
  });

  it('moves a folder to the trash with the same request as today', async () => {
    render(<DocumentsPage />);
    await screen.findByText('logo.png');
    docCalls.length = 0;
    await menuOn('Contracts', 'Delete');
    await settle();
    expect(recorded()).toMatchSnapshot();
  });

  it('moves a file with the same requests as today', async () => {
    render(<DocumentsPage />);
    await screen.findByText('logo.png');
    await menuOn('logo.png', 'Move to…');
    const dialog = await screen.findByRole('dialog');
    fireEvent.click(await within(dialog).findByRole('button', { name: /Quotations/ }));
    await settle();
    docCalls.length = 0;
    fireEvent.click(within(dialog).getByRole('button', { name: 'Move here' }));
    await settle();
    expect(recorded()).toMatchSnapshot();
  });

  it('downloads a file and a folder from the same places as today', async () => {
    URL.createObjectURL = vi.fn(() => 'blob:x');
    URL.revokeObjectURL = vi.fn();
    render(<DocumentsPage />);
    await screen.findByText('logo.png');
    docCalls.length = 0;
    await menuOn('invoice-2026-11.pdf', 'Download');
    await settle();
    await menuOn('Quotations', 'Download ZIP');
    await settle();
    expect(recorded()).toMatchSnapshot();
  });

  it('renders the trash and deletes forever only after DELETE is typed, as today', async () => {
    const { container } = render(<DocumentsPage />);
    await screen.findByText('logo.png');
    fireEvent.click(screen.getByRole('button', { name: /Trash/ }));
    await screen.findByText('scan-0042.jpg');
    await settle();
    expect(parityHtml(container)).toMatchSnapshot();

    fireEvent.click(screen.getByLabelText('Select Old drafts'));
    fireEvent.click(screen.getByLabelText('Select scan-0042.jpg'));
    fireEvent.click(screen.getByRole('button', { name: /Delete forever/ }));
    const dialog = await screen.findByRole('dialog');
    expect(parityHtml(dialog)).toMatchSnapshot();
    docCalls.length = 0;
    const confirm = within(dialog).getByRole('button', { name: 'Delete forever' });
    fireEvent.change(within(dialog).getByPlaceholderText('DELETE'), { target: { value: 'delete' } });
    fireEvent.click(confirm);
    await settle();
    expect(recorded()).toEqual([]);
    fireEvent.change(within(dialog).getByPlaceholderText('DELETE'), { target: { value: 'DELETE' } });
    fireEvent.click(confirm);
    await settle();
    expect(recorded()).toMatchSnapshot();
  });

  it('restores from the trash with the same requests as today', async () => {
    render(<DocumentsPage />);
    await screen.findByText('logo.png');
    fireEvent.click(screen.getByRole('button', { name: /Trash/ }));
    await screen.findByText('scan-0042.jpg');
    fireEvent.click(screen.getByLabelText('Select Old drafts'));
    fireEvent.click(screen.getByLabelText('Select scan-0042.jpg'));
    docCalls.length = 0;
    fireEvent.click(screen.getByRole('button', { name: /Restore/ }));
    await settle();
    expect(recorded()).toMatchSnapshot();
  });
});

describe('switch-off parity: share dialog', () => {
  // The old dialog renders today's UTC day as the date field's `min`, so the
  // snapshot holds the day it was recorded. Pin the clock to that day: only
  // `Date` is faked, the timers the rendering waits on stay real.
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(new Date('2026-11-18T04:00:00Z'));
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('renders a share with an expiry as today', async () => {
    render(<ShareDialog target={{ kind: 'folder', id: 'fld-1', name: 'Quotations' }} ceiling="view" canManage onClose={() => {}} />);
    const dialog = await screen.findByRole('dialog');
    await screen.findByTestId('share-url');
    await settle();
    expect(parityHtml(dialog)).toMatchSnapshot();
  });

  it('a picked expiry day sends the same instant as today', async () => {
    render(<ShareDialog target={{ kind: 'folder', id: 'fld-1', name: 'Quotations' }} ceiling="view" canManage onClose={() => {}} />);
    const input = await screen.findByLabelText('Expiry date', { selector: 'input' });
    docCalls.length = 0;
    fireEvent.change(input, { target: { value: '2027-02-14' } });
    await settle();
    expect(recorded()).toEqual([['updateShare', 'shr-1', { expiresAt: '2027-02-14T23:59:59.000Z' }]]);
    expect(share().id).toBe('shr-1');
  });
});

describe('switch-off parity: shared links', () => {
  it('renders the shared links list as today', async () => {
    const { container } = render(<DocumentSharesPage />);
    await screen.findByText('invoice-2026-11.pdf');
    await settle();
    expect(parityHtml(container)).toMatchSnapshot();
    expect(recorded()).toMatchSnapshot();
  });

  it('bulk revoke asks for REVOKE and sends the same request as today', async () => {
    render(<DocumentSharesPage />);
    await screen.findByText('invoice-2026-11.pdf');
    const boxes = screen.getAllByRole('checkbox');
    fireEvent.click(boxes[1]);
    fireEvent.click(boxes[2]);
    await settle();
    const trigger = screen.getByRole('button', { name: 'Bulk actions' });
    fireEvent.pointerDown(trigger, { button: 0, clientX: 10, clientY: 10 });
    fireEvent.click(await screen.findByRole('menuitem', { name: /Revoke/ }));
    const dialog = await screen.findByRole('alertdialog').catch(() => screen.findByRole('dialog'));
    expect(parityHtml(dialog)).toMatchSnapshot();
    docCalls.length = 0;
    const input = within(dialog).getByRole('textbox');
    fireEvent.change(input, { target: { value: 'REVOKE' } });
    const go = within(dialog).getAllByRole('button', { name: /Revoke/ });
    fireEvent.click(go[go.length - 1]);
    await settle();
    expect(recorded()).toMatchSnapshot();
  });
});

describe('switch-off parity: document types', () => {
  it('renders the types list as today', async () => {
    const { container } = render(<DocumentTypesPage />);
    await screen.findByText('Supplier and customer invoices');
    await settle();
    expect(parityHtml(container)).toMatchSnapshot();
  });

  it('creates a type with the same request as today', async () => {
    docSearch.value = 'edit=new';
    render(<DocumentTypesPage />);
    const dialog = await screen.findByRole('dialog');
    await settle();
    expect(parityHtml(dialog)).toMatchSnapshot();
    fireEvent.change(within(dialog).getByLabelText('Name *'), { target: { value: ' Receipt ' } });
    fireEvent.change(within(dialog).getByLabelText('Description'), { target: { value: '' } });
    fireEvent.change(within(dialog).getByLabelText('Allowed extensions'), { target: { value: '.PDF, jpg,, ' } });
    fireEvent.change(within(dialog).getByLabelText('Max file size (MB)'), { target: { value: '15' } });
    docCalls.length = 0;
    fireEvent.click(within(dialog).getByRole('button', { name: 'Create type' }));
    await settle();
    expect(recorded()).toMatchSnapshot();
  });

  it('edits a type with the same request as today', async () => {
    docSearch.value = 'edit=typ-1';
    render(<DocumentTypesPage />);
    const dialog = await screen.findByRole('dialog');
    await within(dialog).findByDisplayValue('Invoice');
    fireEvent.change(within(dialog).getByLabelText('Max file size (MB)'), { target: { value: '' } });
    docCalls.length = 0;
    fireEvent.click(within(dialog).getByRole('button', { name: 'Save type' }));
    await settle();
    expect(recorded()).toMatchSnapshot();
  });
});

describe('switch-off parity: document settings', () => {
  it('renders the settings as today and saves the same body', async () => {
    const { container } = render(<DocumentSettingsPage />);
    await screen.findByDisplayValue('2048');
    await settle();
    expect(parityHtml(container)).toMatchSnapshot();
    fireEvent.change(screen.getByLabelText('Storage quota (MB)'), { target: { value: '' } });
    fireEvent.change(screen.getByLabelText('Default max file size (MB)'), { target: { value: '30' } });
    docCalls.length = 0;
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    await settle();
    expect(recorded()).toMatchSnapshot();
  });
});

describe('switch-off parity: storage migration wizard', () => {
  it('renders the confirm step as today and starts only once the name matches', async () => {
    render(<StorageMigrationWizard open onClose={() => docCalls.push(['onClose'])} onStarted={(j) => docCalls.push(['onStarted', j])} />);
    const dialog = await screen.findByRole('dialog');
    expect(parityHtml(dialog)).toMatchSnapshot();
    docCalls.length = 0;
    fireEvent.change(within(dialog).getByLabelText(/to confirm/), { target: { value: 'acme' } });
    expect(recorded()).toEqual([['migration.setConfirmValue', 'acme']]);
  });

  it('starts the migration with the same calls as today', async () => {
    m.migration = migration({ confirmValue: 'acme-files-2027', canStart: true });
    render(<StorageMigrationWizard open onClose={() => docCalls.push(['onClose'])} onStarted={(j) => docCalls.push(['onStarted', j])} />);
    const dialog = await screen.findByRole('dialog');
    docCalls.length = 0;
    fireEvent.click(within(dialog).getByRole('button', { name: /Start migration/ }));
    await settle();
    expect(recorded()).toMatchSnapshot();
  });

  it('renders the test step as today', async () => {
    m.migration = migration({ step: 'test' });
    render(<StorageMigrationWizard open onClose={() => {}} onStarted={() => {}} />);
    const dialog = await screen.findByRole('dialog');
    expect(parityHtml(dialog)).toMatchSnapshot();
  });
});
