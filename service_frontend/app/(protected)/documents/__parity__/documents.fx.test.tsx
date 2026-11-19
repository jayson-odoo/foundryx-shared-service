/**
 * The documents pages under the Foundryx UIUX switch (slice W3-DOCS): every
 * write sends exactly what the switch-off page sends for the same input
 * (upload, new folder, rename, move, trash, restore, delete forever, share
 * expiry, revoke, document types, settings, storage migration), downloads
 * fetch the same things, and the typed confirms send nothing before the
 * typed text matches.
 */
import type { ReactElement, ReactNode } from 'react';
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { FX_DEFAULT_THEME } from '@/lib/fx/cookies';
import { FxProvider } from '@/providers/fx-provider';
import { TooltipsProvider } from '@/providers/tooltips-provider';
import { SettingsProvider } from '@/providers/settings-provider';
import { resetPageActionsForTests } from '@/components/fx/actions/page-actions-context';
import { docCalls, docSearch, docToasts, migration, recorded } from './doc-mocks';
import { share } from './fixtures';

const m = vi.hoisted(() => ({ migration: null as unknown, shareOver: null as unknown }));

vi.mock('@/services/document-service', async () => {
  const mod = (await import('./doc-mocks')).documentServiceModule();
  const { share: mk } = await import('./fixtures');
  const ensure = mod.documentService.ensureShare;
  mod.documentService.ensureShare = (...args: unknown[]) =>
    m.shareOver ? (ensure(...args), Promise.resolve(mk(m.shareOver as object))) : ensure(...args);
  return mod;
});
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

import DocumentsPage from '../page';
import DocumentSharesPage from '../shares/page';
import DocumentTypesPage from '../types/page';
import DocumentSettingsPage from '../settings/page';
import { documentSettingsBody } from '../settings/fx-document-settings';
import { ShareDialog } from '@/components/platform/document-drive/share-dialog';
import { shareExpiryInstant, shareExpiryMinDay } from '@/components/platform/document-drive/fx-share-advanced';
import { fxPurgeExpected, fxTargetsName } from '@/components/platform/document-drive/fx-drive-words';
import { StorageMigrationWizard } from '@/components/platform/storage-migration-wizard';

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

/** Requests only (toasts and reloads differ by design, never requests). */
function writes(): unknown[] {
  return recorded().filter((c) => {
    const name = (c as unknown[])[0] as string;
    return !name.startsWith('toast.') && !['listFolder', 'getSettings', 'listTrash', 'listShares', 'listTypes', 'router.push'].includes(name);
  });
}

function toasts(kind: string) {
  return docToasts.filter((t) => t[0] === kind).map((t) => t[1] as Record<string, unknown>);
}

async function mount(fx: boolean, ui: ReactElement) {
  resetPageActionsForTests();
  let view!: ReturnType<typeof render>;
  await act(async () => {
    view = render(<Wrap fx={fx}>{ui}</Wrap>);
  });
  return view;
}

/** Runs `act` with the switch off, then on, on a fresh page each time, and
 *  returns the requests each sent. */
async function both(ui: () => ReactElement, act: (fx: boolean) => Promise<void>, ready: () => Promise<unknown>) {
  const out: unknown[][] = [];
  for (const fx of [false, true]) {
    const view = await mount(fx, ui());
    await ready();
    await settle();
    docCalls.length = 0;
    docToasts.length = 0;
    await act(fx);
    await settle();
    out.push(writes());
    if (fx) break;
    view.unmount();
  }
  return { off: out[0], on: out[1] };
}

async function menuOn(name: string, item: string) {
  const entry = document.querySelector(`[data-name="${name}"]`) as HTMLElement;
  fireEvent.contextMenu(entry, { clientX: 20, clientY: 20 });
  fireEvent.click(await screen.findByRole('menuitem', { name: item }));
}

const driveReady = () => screen.findByText('logo.png');

beforeEach(() => {
  docCalls.length = 0;
  docToasts.length = 0;
  docSearch.value = '';
  m.migration = migration();
  m.shareOver = null;
});

describe('drive: same writes in both looks', () => {
  it('Upload hands the same files and options to the upload queue', async () => {
    const files = [new File(['a'], 'a.pdf'), new File(['b'], 'b.png')];
    const { off, on } = await both(
      () => <DocumentsPage />,
      async (fx) => {
        if (fx) fireEvent.click(screen.getByRole('button', { name: 'Upload files to Drive' }));
        else fireEvent.click(screen.getByRole('button', { name: /Upload/ }));
        const dialog = await screen.findByRole('dialog');
        const input = dialog.querySelector('input[type="file"]') as HTMLInputElement;
        fireEvent.change(input, { target: { files } });
      },
      driveReady,
    );
    expect(off).toEqual([['uploads.enqueue', ['a.pdf', 'b.png'], { attachmentTypeId: null, folderId: null }]]);
    expect(on).toEqual(off);
  });

  it('New folder sends the same request', async () => {
    const { off, on } = await both(
      () => <DocumentsPage />,
      async () => {
        fireEvent.click(screen.getByRole('button', { name: 'New folder' }));
        fireEvent.change(await screen.findByLabelText('Folder name'), { target: { value: '  Receipts  ' } });
        fireEvent.click(screen.getByRole('button', { name: 'Create folder' }));
      },
      driveReady,
    );
    expect(off).toEqual([['createFolder', { name: 'Receipts', parentId: null }]]);
    expect(on).toEqual(off);
    expect(toasts('fxDone')).toEqual([{ what: 'Folder Receipts created', byWhom: 'Kay Tan' }]);
  });

  it('Rename sends the same request, and Undo renames it back', async () => {
    const { off, on } = await both(
      () => <DocumentsPage />,
      async () => {
        await menuOn('invoice-2026-11.pdf', 'Rename');
        fireEvent.change(await screen.findByLabelText('Name'), { target: { value: 'invoice-nov.pdf' } });
        fireEvent.click(screen.getByRole('button', { name: 'Rename file' }));
      },
      driveReady,
    );
    expect(off).toEqual([['renameFile', 'fil-1', { name: 'invoice-nov.pdf' }]]);
    expect(on).toEqual(off);
    const done = toasts('fxDone')[0];
    expect(done.what).toBe('invoice-2026-11.pdf renamed to invoice-nov.pdf');
    docCalls.length = 0;
    await act(async () => (done.undo as () => void)());
    await settle();
    expect(writes()).toEqual([['renameFile', 'fil-1', { name: 'invoice-2026-11.pdf' }]]);
  });

  it('Move sends the same request, and Undo moves it back', async () => {
    const { off, on } = await both(
      () => <DocumentsPage />,
      async () => {
        await menuOn('logo.png', 'Move to…');
        const dialog = await screen.findByRole('dialog');
        fireEvent.click(await within(dialog).findByRole('button', { name: /Quotations/ }));
        await settle();
        fireEvent.click(within(dialog).getByRole('button', { name: 'Move here' }));
      },
      driveReady,
    );
    expect(off).toEqual([['moveFiles', ['fil-2'], { targetFolderId: 'fld-1' }]]);
    expect(on).toEqual(off);
    const done = toasts('fxDone')[0];
    expect(done.what).toBe('logo.png moved');
    docCalls.length = 0;
    await act(async () => (done.undo as () => void)());
    await settle();
    expect(writes()).toEqual([['moveFiles', ['fil-2'], { targetFolderId: null }]]);
  });

  it('Move to Trash sends the same request as Delete, and Undo restores it', async () => {
    const { off, on } = await both(
      () => <DocumentsPage />,
      async (fx) => menuOn('Contracts', fx ? 'Move to Trash' : 'Delete'),
      driveReady,
    );
    expect(off).toEqual([['deleteFolders', ['fld-2']]]);
    expect(on).toEqual(off);
    const done = toasts('fxDone')[0];
    expect(done).toMatchObject({ what: 'Contracts moved to Trash', byWhom: 'Kay Tan' });
    docCalls.length = 0;
    await act(async () => (done.undo as () => void)());
    await settle();
    expect(writes()).toEqual([['restoreFolders', ['fld-2']]]);
  });

  it('the selection bar runs the right-click handlers: Move to Trash for two ticked entries', async () => {
    const { off, on } = await both(
      () => <DocumentsPage />,
      async (fx) => {
        fireEvent.click(screen.getByLabelText('Select Contracts'));
        fireEvent.click(screen.getByLabelText('Select logo.png'));
        if (fx) {
          const bar = screen.getByRole('toolbar', { name: 'Selection' });
          expect(within(bar).getByText('2 selected')).toBeInTheDocument();
          fireEvent.click(within(bar).getByRole('button', { name: 'Move 2 items to Trash' }));
        } else {
          await menuOn('logo.png', 'Delete (2)');
        }
      },
      driveReady,
    );
    expect(off).toEqual([['deleteFolders', ['fld-2']], ['deleteFiles', ['fil-2']]]);
    expect(on).toEqual(off);
  });

  it('downloads fetch the same file and ask for the same ZIP', async () => {
    URL.createObjectURL = vi.fn(() => 'blob:x');
    URL.revokeObjectURL = vi.fn();
    const { off, on } = await both(
      () => <DocumentsPage />,
      async (fx) => {
        if (fx) {
          fireEvent.click(screen.getByLabelText('Select invoice-2026-11.pdf'));
          fireEvent.click(within(screen.getByRole('toolbar', { name: 'Selection' })).getByRole('button', { name: 'Download' }));
          await settle();
          fireEvent.click(screen.getByLabelText('Select invoice-2026-11.pdf'));
        } else {
          await menuOn('invoice-2026-11.pdf', 'Download');
          await settle();
        }
        await menuOn('Quotations', 'Download ZIP');
      },
      driveReady,
    );
    expect(off).toEqual([['downloadFile', 'fil-1'], ['downloads.requestZip', { fileIds: [], folderIds: ['fld-1'] }]]);
    expect(on).toEqual(off);
  });

  it('shows Upload as the red action only in the drive itself', async () => {
    await mount(true, <DocumentsPage />);
    await driveReady();
    expect(screen.getByRole('button', { name: 'Upload files to Drive' })).toBeInTheDocument();
    expect(screen.queryByText('Right-click for actions')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: /Trash/ }));
    await screen.findByText('scan-0042.jpg');
    expect(screen.queryByRole('button', { name: 'Upload files to Drive' })).toBeNull();
  });
});

describe('trash: same writes in both looks, typed confirm', () => {
  async function openTrash() {
    fireEvent.click(screen.getByRole('button', { name: /Trash/ }));
    await screen.findByText('scan-0042.jpg');
  }

  it('Restore sends the same requests, and Undo puts them back in the Trash', async () => {
    const { off, on } = await both(
      () => <DocumentsPage />,
      async (fx) => {
        await openTrash();
        fireEvent.click(screen.getByLabelText('Select Old drafts'));
        fireEvent.click(screen.getByLabelText('Select scan-0042.jpg'));
        if (fx) fireEvent.click(screen.getByRole('button', { name: 'Restore 2 items' }));
        else fireEvent.click(screen.getByRole('button', { name: /Restore/ }));
      },
      driveReady,
    );
    expect(off).toEqual([['restoreFolders', ['fld-9']], ['restoreFiles', ['fil-9']]]);
    expect(on).toEqual(off);
    const done = toasts('fxDone')[0];
    expect(done.what).toBe('2 items restored');
    docCalls.length = 0;
    await act(async () => (done.undo as () => void)());
    await settle();
    expect(writes()).toEqual([['deleteFolders', ['fld-9']], ['deleteFiles', ['fil-9']]]);
  });

  it('Delete forever types the number of items and sends nothing before it matches', async () => {
    const { off, on } = await both(
      () => <DocumentsPage />,
      async (fx) => {
        await openTrash();
        fireEvent.click(screen.getByLabelText('Select Old drafts'));
        fireEvent.click(screen.getByLabelText('Select scan-0042.jpg'));
        if (fx) {
          fireEvent.click(screen.getByRole('button', { name: 'Delete 2 items forever' }));
          const dialog = await screen.findByRole('alertdialog');
          expect(within(dialog).getByText('Delete 2 items forever?')).toBeInTheDocument();
          const go = within(dialog).getByRole('button', { name: 'Delete 2 items forever' });
          fireEvent.click(go);
          fireEvent.change(within(dialog).getByLabelText('Type "2"'), { target: { value: 'DELETE' } });
          fireEvent.click(go);
          await settle();
          expect(writes()).toEqual([]);
          fireEvent.change(within(dialog).getByLabelText('Type "2"'), { target: { value: '2' } });
          fireEvent.click(go);
        } else {
          fireEvent.click(screen.getByRole('button', { name: /Delete forever/ }));
          const dialog = await screen.findByRole('dialog');
          fireEvent.change(within(dialog).getByPlaceholderText('DELETE'), { target: { value: 'DELETE' } });
          fireEvent.click(within(dialog).getByRole('button', { name: 'Delete forever' }));
        }
      },
      driveReady,
    );
    expect(off).toEqual([['purgeFolders', ['fld-9']], ['purgeFiles', ['fil-9']]]);
    expect(on).toEqual(off);
    expect(toasts('fxDone')[0]).toEqual({ what: '2 items deleted forever', byWhom: 'Kay Tan' });
  });

  it('Delete forever on one entry types its name', async () => {
    await mount(true, <DocumentsPage />);
    await driveReady();
    await openTrash();
    fireEvent.click(screen.getByLabelText('Select scan-0042.jpg'));
    fireEvent.click(screen.getByRole('button', { name: 'Delete 1 item forever' }));
    const dialog = await screen.findByRole('alertdialog');
    const go = within(dialog).getByRole('button', { name: 'Delete forever' });
    docCalls.length = 0;
    fireEvent.change(within(dialog).getByLabelText('Type "scan-0042.jpg"'), { target: { value: 'scan-0042' } });
    fireEvent.click(go);
    await settle();
    expect(writes()).toEqual([]);
    fireEvent.change(within(dialog).getByLabelText('Type "scan-0042.jpg"'), { target: { value: 'scan-0042.jpg' } });
    fireEvent.click(go);
    await settle();
    expect(writes()).toEqual([['purgeFiles', ['fil-9']]]);
  });

  it('names and typed values come from the entries', () => {
    const nameOf = (kind: 'folder' | 'file', id: string) => (kind === 'file' && id === 'f' ? 'a.pdf' : undefined);
    expect(fxTargetsName({ folderIds: [], fileIds: ['f'] }, nameOf)).toBe('a.pdf');
    expect(fxPurgeExpected({ folderIds: [], fileIds: ['f'] }, nameOf)).toBe('a.pdf');
    expect(fxTargetsName({ folderIds: ['x'], fileIds: ['f'] }, nameOf)).toBe('2 items');
    expect(fxPurgeExpected({ folderIds: ['x', 'y'], fileIds: ['f'] }, nameOf)).toBe('3');
  });
});

describe('share dialog: expiry in the date field sends the same instant', () => {
  it('shareExpiryInstant is what the date input sends; the bound is the UTC day', () => {
    expect(shareExpiryInstant('2027-02-14')).toBe(new Date('2027-02-14T23:59:59Z').toISOString());
    expect(shareExpiryInstant('2027-02-14')).toBe('2027-02-14T23:59:59.000Z');
    expect(shareExpiryMinDay(new Date('2026-11-19T20:30:00Z'))).toBe('2026-11-19');
    expect(shareExpiryMinDay(new Date('2026-11-19T16:30:00+08:00'))).toBe('2026-11-19');
  });

  const target = { kind: 'folder' as const, id: 'fld-1', name: 'Quotations' };

  it('a day typed in the new field patches the same body as the same day in today\'s field', async () => {
    const { off, on } = await both(
      () => <ShareDialog target={target} ceiling="view" canManage onClose={() => {}} />,
      async (fx) => {
        if (fx) {
          const input = screen.getByRole('textbox', { name: 'Expiry date' });
          fireEvent.change(input, { target: { value: '14/02/2027' } });
          fireEvent.blur(input);
        } else {
          fireEvent.change(screen.getByLabelText('Expiry date', { selector: 'input' }), { target: { value: '2027-02-14' } });
        }
      },
      () => screen.findByTestId('share-url'),
    );
    expect(off).toEqual([['updateShare', 'shr-1', { expiresAt: '2027-02-14T23:59:59.000Z' }]]);
    expect(on).toEqual(off);
  });

  it('a day picked from the calendar sends the same instant', async () => {
    await mount(true, <ShareDialog target={target} ceiling="view" canManage onClose={() => {}} />);
    await screen.findByTestId('share-url');
    fireEvent.click(screen.getByRole('button', { name: 'Open calendar' }));
    const day = await screen.findByRole('button', { name: /January 20/ }).catch(() => screen.findByText('20'));
    docCalls.length = 0;
    fireEvent.click(day);
    await settle();
    expect(writes()).toEqual([['updateShare', 'shr-1', { expiresAt: '2027-01-20T23:59:59.000Z' }]]);
  });

  it('shows when the link stops working, 12-hour, in the viewer\'s zone', async () => {
    await mount(true, <ShareDialog target={target} ceiling="view" canManage onClose={() => {}} />);
    await screen.findByTestId('share-url');
    expect(screen.getByTestId('share-expiry-moment').textContent).toBe('Stops working 16 Jan 2027, 7:59 am');
  });

  it('turning Expiry on opens the field and sends nothing until a day is picked', async () => {
    m.shareOver = { expiresAt: null };
    await mount(true, <ShareDialog target={target} ceiling="view" canManage onClose={() => {}} />);
    await screen.findByTestId('share-url');
    docCalls.length = 0;
    fireEvent.click(screen.getByRole('switch', { name: 'Expiry date' }));
    await settle();
    expect(writes()).toEqual([]);
    const input = screen.getByRole('textbox', { name: 'Expiry date' });
    fireEvent.change(input, { target: { value: '14 Feb 2027' } });
    fireEvent.blur(input);
    await settle();
    expect(writes()).toEqual([['updateShare', 'shr-1', { expiresAt: '2027-02-14T23:59:59.000Z' }]]);
  });

  it('turning Expiry off clears it with today\'s request', async () => {
    const { off, on } = await both(
      () => <ShareDialog target={target} ceiling="view" canManage onClose={() => {}} />,
      async () => {
        fireEvent.click(screen.getByRole('switch', { name: 'Expiry date' }));
      },
      () => screen.findByTestId('share-url'),
    );
    expect(off).toEqual([['updateShare', 'shr-1', { expiresAt: null }]]);
    expect(on).toEqual(off);
  });

  it('a password is masked and set with the request today\'s field sends', async () => {
    m.shareOver = { hasPassword: false };
    await mount(true, <ShareDialog target={target} ceiling="view" canManage onClose={() => {}} />);
    await screen.findByTestId('share-url');
    fireEvent.click(screen.getByRole('switch', { name: 'Password' }));
    const pw = screen.getByLabelText('Share password') as HTMLInputElement;
    expect(pw.type).toBe('password');
    fireEvent.change(pw, { target: { value: 's3cret pass' } });
    docCalls.length = 0;
    fireEvent.click(screen.getByRole('button', { name: 'Set password' }));
    await settle();
    expect(writes()).toEqual([['updateShare', 'shr-1', { password: 's3cret pass' }]]);
    expect(share().id).toBe('shr-1');
  });
});

describe('shared links: bulk revoke types the number of links', () => {
  it('sends the same request, nothing before the count is typed, and a toast without the link', async () => {
    const { off, on } = await both(
      () => <DocumentSharesPage />,
      async (fx) => {
        const boxes = screen.getAllByRole('checkbox');
        fireEvent.click(boxes[1]);
        fireEvent.click(boxes[2]);
        await settle();
        if (fx) {
          fireEvent.click(within(screen.getByRole('toolbar', { name: 'Selection' })).getByRole('button', { name: 'Revoke' }));
          const dialog = await screen.findByRole('alertdialog');
          expect(within(dialog).getByText('Revoke 2 links?')).toBeInTheDocument();
          const go = within(dialog).getByRole('button', { name: 'Revoke 2 links' });
          fireEvent.change(within(dialog).getByLabelText('Type "2"'), { target: { value: 'REVOKE' } });
          fireEvent.click(go);
          await settle();
          expect(writes()).toEqual([]);
          fireEvent.change(within(dialog).getByLabelText('Type "2"'), { target: { value: '2' } });
          fireEvent.click(go);
        } else {
          fireEvent.pointerDown(screen.getByRole('button', { name: 'Bulk actions' }), { button: 0, clientX: 10, clientY: 10 });
          fireEvent.click(await screen.findByRole('menuitem', { name: /Revoke/ }));
          const dialog = await screen.findByRole('alertdialog').catch(() => screen.findByRole('dialog'));
          fireEvent.change(within(dialog).getByRole('textbox'), { target: { value: 'REVOKE' } });
          const go = within(dialog).getAllByRole('button', { name: /Revoke/ });
          fireEvent.click(go[go.length - 1]);
        }
      },
      () => screen.findAllByText('invoice-2026-11.pdf'),
    );
    expect(off).toEqual([['revokeShares', ['shr-1', 'shr-2']]]);
    expect(on).toEqual(off);
    const done = toasts('fxDone');
    expect(done).toEqual([{ what: '2 links revoked', byWhom: 'Kay Tan' }]);
    expect(JSON.stringify(docToasts)).not.toMatch(/tok-parity|public\/documents/);
  });
});

describe('document types: same writes in both looks', () => {
  it('creates a type with the same body', async () => {
    docSearch.value = 'edit=new';
    const { off, on } = await both(
      () => <DocumentTypesPage />,
      async () => {
        const dialog = screen.getByRole('dialog');
        fireEvent.change(within(dialog).getByLabelText('Name *'), { target: { value: ' Receipt ' } });
        fireEvent.change(within(dialog).getByLabelText('Allowed extensions'), { target: { value: '.PDF, jpg,, ' } });
        fireEvent.change(within(dialog).getByLabelText('Max file size (MB)'), { target: { value: '15' } });
        fireEvent.click(within(dialog).getByRole('button', { name: 'Create type' }));
      },
      () => screen.findByRole('dialog'),
    );
    expect(off).toEqual([['createType', { name: 'Receipt', description: null, allowedExts: ['pdf', 'jpg'], maxMb: 15 }]]);
    expect(on).toEqual(off);
    expect(toasts('fxDone')).toEqual([{ what: 'Document type Receipt added', byWhom: 'Kay Tan' }]);
  });

  it('edits a type with the same body', async () => {
    docSearch.value = 'edit=typ-1';
    const { off, on } = await both(
      () => <DocumentTypesPage />,
      async () => {
        const dialog = screen.getByRole('dialog');
        fireEvent.change(within(dialog).getByLabelText('Max file size (MB)'), { target: { value: '' } });
        fireEvent.click(within(dialog).getByRole('button', { name: 'Save type' }));
      },
      () => screen.findByDisplayValue('Invoice'),
    );
    expect(off).toEqual([['updateType', 'typ-1', { name: 'Invoice', description: 'Supplier and customer invoices', allowedExts: ['pdf', 'png'], maxMb: null }]]);
    expect(on).toEqual(off);
  });
});

describe('document settings: same body in both looks', () => {
  it('Save settings (the red action) sends what Save changes sends', async () => {
    const { off, on } = await both(
      () => <DocumentSettingsPage />,
      async (fx) => {
        fireEvent.change(screen.getByLabelText('Storage quota (MB)'), { target: { value: '' } });
        fireEvent.change(screen.getByLabelText('Default max file size (MB)'), { target: { value: '30' } });
        fireEvent.click(screen.getByRole('button', { name: fx ? 'Save document settings' : 'Save changes' }));
      },
      () => screen.findByDisplayValue('2048'),
    );
    expect(off).toEqual([['updateSettings', { defaultMaxFileMb: 30, storageQuotaMb: null, publicSharing: 'view' }]]);
    expect(on).toEqual(off);
    expect(toasts('fxDone')).toEqual([{ what: 'Document settings saved', byWhom: 'Kay Tan' }]);
  });

  it('the body builder matches today\'s rules', () => {
    expect(documentSettingsBody('', ' ', 'off')).toEqual({ defaultMaxFileMb: 0, storageQuotaMb: null, publicSharing: 'off' });
    expect(documentSettingsBody('abc', '0', 'edit')).toEqual({ defaultMaxFileMb: 0, storageQuotaMb: 0, publicSharing: 'edit' });
  });
});

describe('storage migration: typed bucket name', () => {
  it('Start migration sends nothing until the bucket name matches', async () => {
    await mount(true, <StorageMigrationWizard open onClose={() => {}} onStarted={() => {}} />);
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText('Type the bucket name to confirm.')).toBeInTheDocument();
    docCalls.length = 0;
    fireEvent.click(within(dialog).getByRole('button', { name: /Start migration/ }));
    await settle();
    expect(recorded()).toEqual([]);
    fireEvent.change(within(dialog).getByLabelText('Type "acme-files-2027"'), { target: { value: 'acme' } });
    expect(recorded()).toEqual([['migration.setConfirmValue', 'acme']]);
  });

  it('starts with the same calls once it matches', async () => {
    const run = async (fx: boolean) => {
      m.migration = migration({ confirmValue: 'acme-files-2027', canStart: true });
      const view = await mount(fx, <StorageMigrationWizard open onClose={() => docCalls.push(['onClose'])} onStarted={(j) => docCalls.push(['onStarted', j])} />);
      const dialog = await screen.findByRole('dialog');
      docCalls.length = 0;
      fireEvent.click(within(dialog).getByRole('button', { name: /Start migration/ }));
      await settle();
      const out = writes();
      view.unmount();
      return out;
    };
    const off = await run(false);
    docToasts.length = 0;
    const on = await run(true);
    expect(off).toEqual([['migration.start'], ['onStarted', { id: 'job-1' }], ['onClose']]);
    expect(on).toEqual(off);
    expect(toasts('fxDone')).toEqual([{ what: 'Storage migration to acme-files-2027 started', byWhom: 'Kay Tan' }]);
  });
});
