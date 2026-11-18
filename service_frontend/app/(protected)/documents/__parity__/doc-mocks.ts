/**
 * Recording stand-ins for the documents pages' services (Foundryx UIUX,
 * slice W3-DOCS). Every call a page makes is pushed onto `docCalls` with its
 * arguments, so a test can compare what both looks send. Test files wire
 * these in with `vi.mock(path, async () => (await import('./doc-mocks')).x())`.
 */
import {
  ROOT_LISTING,
  SETTINGS,
  SHARES,
  TRASH,
  TYPES,
  docType,
  folder,
  share,
} from './fixtures';

export const docCalls: unknown[] = [];

/** Every toast as called (functions kept), for invoking an Undo. */
export const docToasts: unknown[][] = [];

/** Next value `useSearchParams()` returns (types page `?edit=`). */
export const docSearch = { value: '' };

function rec<R>(name: string, result: () => R) {
  return (...args: unknown[]) => {
    docCalls.push([name, ...args.map((a) => (a instanceof Set ? Array.from(a) : a))]);
    return Promise.resolve(result());
  };
}

export function documentServiceModule() {
  return {
    documentService: {
      listFolder: rec('listFolder', () =>
        structuredClone({
          ...ROOT_LISTING,
          folders: ROOT_LISTING.folders,
        }),
      ),
      getSettings: rec('getSettings', () => structuredClone(SETTINGS)),
      updateSettings: rec('updateSettings', () => structuredClone(SETTINGS)),
      createFolder: rec('createFolder', () => folder({ id: 'fld-new', name: 'New' })),
      renameFolder: rec('renameFolder', () => undefined),
      renameFile: rec('renameFile', () => undefined),
      moveFolders: rec('moveFolders', () => undefined),
      moveFiles: rec('moveFiles', () => undefined),
      deleteFolders: rec('deleteFolders', () => undefined),
      deleteFiles: rec('deleteFiles', () => undefined),
      listTrash: rec('listTrash', () => structuredClone(TRASH)),
      restoreFolders: rec('restoreFolders', () => undefined),
      restoreFiles: rec('restoreFiles', () => undefined),
      purgeFolders: rec('purgeFolders', () => undefined),
      purgeFiles: rec('purgeFiles', () => undefined),
      downloadFile: rec('downloadFile', () => new Blob(['x'])),
      previewUrl: rec('previewUrl', () => 'blob:preview'),
      listSharedWithMe: rec('listSharedWithMe', () => []),
      ensureShare: rec('ensureShare', () => share()),
      updateShare: rec('updateShare', () => share()),
      listShareUsers: rec('listShareUsers', () => [
        { id: 'u-2', name: 'Ada Lim', email: 'ada@example.com' },
        { id: 'u-3', name: 'Ben Ong', email: 'ben@example.com' },
      ]),
      listShares: rec('listShares', () => ({ data: structuredClone(SHARES), total: SHARES.length })),
      exportShares: rec('exportShares', () => undefined),
      revokeShares: rec('revokeShares', () => undefined),
      listTypes: rec('listTypes', () => ({ data: structuredClone(TYPES), total: TYPES.length })),
      exportTypes: rec('exportTypes', () => undefined),
      getType: rec('getType', () => docType()),
      createType: rec('createType', () => docType({ id: 'typ-new' })),
      updateType: rec('updateType', () => docType()),
    },
  };
}

export function uploadManagerModule() {
  const enqueue = (...args: unknown[]) => {
    const [files, options] = args as [File[], unknown];
    docCalls.push(['uploads.enqueue', files.map((f) => f.name), options]);
  };
  const value = {
    items: [],
    activeCount: 0,
    open: false,
    completedVersion: 0,
    setOpen: () => {},
    enqueue,
    resolveConflict: () => {},
    retry: () => {},
    remove: () => {},
    clearFinished: () => {},
  };
  return {
    useUploadManager: () => value,
    UploadManagerProvider: ({ children }: { children: unknown }) => children,
  };
}

export function downloadsModule() {
  const value = {
    jobs: [],
    activeCount: 0,
    open: false,
    setOpen: () => {},
    requestZip: (...args: unknown[]) => {
      docCalls.push(['downloads.requestZip', ...args]);
      return Promise.resolve();
    },
    download: (...args: unknown[]) => {
      docCalls.push(['downloads.download', ...args]);
      return Promise.resolve();
    },
  };
  return {
    useDownloads: () => value,
    DownloadsProvider: ({ children }: { children: unknown }) => children,
  };
}

export function navigationModule() {
  return {
    useRouter: () => ({
      push: (...args: unknown[]) => docCalls.push(['router.push', ...args]),
      replace: () => {},
      prefetch: () => {},
      back: () => {},
      refresh: () => {},
    }),
    usePathname: () => '/documents',
    useSearchParams: () => new URLSearchParams(docSearch.value),
    useParams: () => ({}),
  };
}

export function toastModule() {
  const t =
    (kind: string) =>
    (...args: unknown[]) => {
      docToasts.push([kind, ...args]);
      docCalls.push([`toast.${kind}`, ...args.map((a) => (typeof a === 'object' && a && 'undo' in a ? { ...a, undo: typeof (a as { undo: unknown }).undo } : a))]);
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
}

/** The calls so far as plain JSON (Blob and File become `{}`). */
export function recorded(): unknown[] {
  return JSON.parse(JSON.stringify(docCalls));
}
