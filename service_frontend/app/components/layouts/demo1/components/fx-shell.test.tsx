/**
 * The Foundryx UIUX shell (slice F5) with the switch on: the side panel's icon
 * rail, the top bar with its one Jobs button, the Jobs sheet, merging into the
 * page header on scroll and condensing on phones. (Switch off is pinned by
 * components/fx/__parity__.)
 */
import { useSyncExternalStore, type ReactNode } from 'react';
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { FX_DEFAULT_THEME } from '@/lib/fx/cookies';
import { FX_SETTINGS_STORAGE_KEY } from '@/lib/fx/settings-schema';
import { FxProvider } from '@/providers/fx-provider';
import { TooltipsProvider } from '@/providers/tooltips-provider';
import { PageHeader } from '@/components/platform/page-header';
import { JobsDrawer } from '@/components/platform/jobs-drawer';
import {
  resetPageActionsForTests,
  useRegisterMainAction,
  type FxMainActionSpec,
} from '@/components/fx/actions/page-actions-context';
import { resetJobsSheetForTests } from '@/components/fx/shell/jobs-sheet';
import { FX_RAIL_PIN_KEY } from '@/components/fx/shell/use-rail';
import { resetSystemBannersForTests } from '@/components/fx/banners/banner-store';
import { ThemeButton } from '@/components/fx/theme/theme-button';
import { Header } from './header';
import { Sidebar } from './sidebar';

vi.mock('next/navigation', () => ({
  usePathname: () => '/user-management/users',
  useRouter: () => ({ push: vi.fn(), prefetch: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock('next-auth/react', () => ({
  useSession: () => ({
    data: {
      user: {
        name: 'Alpha Tan',
        email: 'alpha@example.com',
        avatar: null,
        isPlatformTenant: false,
        permissions: [],
      },
    },
    status: 'authenticated',
  }),
  signOut: vi.fn(),
}));

vi.mock('next-themes', () => ({
  useTheme: () => ({ theme: 'light', setTheme: vi.fn(), resolvedTheme: 'light' }),
}));

vi.mock('@/hooks/use-app-store', () => ({
  useInstalledModules: () => ({ ready: true, isActive: () => true }),
}));

vi.mock('@/hooks/use-terminology', () => ({
  useTerminology: () => ({ labelPlural: (k: string) => k, label: (k: string) => k }),
}));

vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({
    can: (key: string) => key !== 'secret.read',
    ready: true,
    permissions: new Set<string>(),
  }),
}));

vi.mock('@/lib/impersonation-store', () => ({
  useImpersonationSession: () => null,
  impersonationStore: { setSession: vi.fn() },
}));

vi.mock('@/services/terminology-service', () => ({
  terminologyService: { getTerminology: vi.fn().mockResolvedValue({}) },
}));

vi.mock('@/config/menu.config', async () => {
  const { Users, Boxes, Settings } = await import('lucide-react');
  return {
    MENU_SIDEBAR: [
      { title: 'Users', path: '/user-management/users', icon: Users },
      {
        title: 'Products',
        icon: Boxes,
        children: [
          { title: 'All products', path: '/products' },
          { title: 'Price lists', path: '/products/prices' },
        ],
      },
      {
        title: 'Settings',
        icon: Settings,
        children: [{ title: 'General', path: '/settings/general' }],
      },
      { title: 'Secret area', path: '/secret', icon: Settings, permission: 'secret.read' },
    ],
    MENU_MEGA: [{ title: 'Home', path: '/' }],
    MENU_MEGA_MOBILE: [{ title: 'Home', path: '/' }],
  };
});

vi.mock('@/providers/settings-provider', () => ({
  useSettings: () => ({
    settings: { layouts: { demo1: { sidebarTheme: 'light', sidebarCollapse: false } } },
    storeOption: vi.fn(),
    setOption: vi.fn(),
  }),
}));

// The four activity sources as one tiny store: open flags and counts.
type Kind = 'uploads' | 'imports' | 'jobs' | 'downloads';
let activity: Record<Kind, boolean> = {
  uploads: false,
  imports: false,
  jobs: false,
  downloads: false,
};
let counts: Record<Kind, number> = { uploads: 1, imports: 2, jobs: 0, downloads: 3 };
const listeners = new Set<() => void>();
function setFlag(kind: Kind, open: boolean) {
  activity = { ...activity, [kind]: open };
  listeners.forEach((listener) => listener());
}
function useActivity() {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    () => activity,
  );
}

vi.mock('@/components/platform/document-drive/upload-manager', () => ({
  useUploadManager: () => {
    const a = useActivity();
    return {
      open: a.uploads,
      setOpen: (v: boolean) => setFlag('uploads', v),
      items: [],
      activeCount: counts.uploads,
      resolveConflict: vi.fn(),
      retry: vi.fn(),
      remove: vi.fn(),
      clearFinished: vi.fn(),
    };
  },
}));
vi.mock('@/components/platform/document-drive/downloads-manager', () => ({
  useDownloads: () => {
    const a = useActivity();
    return {
      open: a.downloads,
      setOpen: (v: boolean) => setFlag('downloads', v),
      jobs: [],
      activeCount: counts.downloads,
      download: vi.fn(),
    };
  },
}));
vi.mock('@/providers/import-activity-provider', () => ({
  useImportActivity: () => {
    const a = useActivity();
    return {
      drawerOpen: a.imports,
      setDrawerOpen: (v: boolean) => setFlag('imports', v),
      jobs: [],
      activeCount: counts.imports,
      openImport: vi.fn(),
      refresh: vi.fn(),
    };
  },
}));
vi.mock('@/providers/jobs-activity-provider', () => ({
  useJobsActivity: () => {
    const a = useActivity();
    return {
      drawerOpen: a.jobs,
      setDrawerOpen: (v: boolean) => setFlag('jobs', v),
      jobs: [],
      activeCount: counts.jobs,
      openMigration: vi.fn(),
      refresh: vi.fn(),
    };
  },
}));

function On({ children }: { children: ReactNode }) {
  return (
    <FxProvider initial initialTheme={FX_DEFAULT_THEME}>
      <TooltipsProvider>{children}</TooltipsProvider>
    </FxProvider>
  );
}

async function settle(ui: ReactNode) {
  let result!: ReturnType<typeof render>;
  await act(async () => {
    result = render(<On>{ui}</On>);
  });
  return result;
}

const desktopWidth = window.innerWidth;
const realMatchMedia = window.matchMedia;

function setScroll(y: number) {
  Object.defineProperty(window, 'scrollY', { configurable: true, value: y });
  act(() => {
    window.dispatchEvent(new Event('scroll'));
  });
}

beforeEach(() => {
  window.localStorage.clear();
  activity = { uploads: false, imports: false, jobs: false, downloads: false };
  counts = { uploads: 1, imports: 2, jobs: 0, downloads: 3 };
  resetJobsSheetForTests();
  resetPageActionsForTests();
  resetSystemBannersForTests();
  setScroll(0);
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  window.matchMedia = realMatchMedia;
  Object.defineProperty(window, 'innerWidth', { configurable: true, value: desktopWidth });
  document.documentElement.removeAttribute('data-fx');
});

describe('side panel: icon rail', () => {
  const rail = () => screen.getByRole('navigation', { name: 'Main menu' });

  it('is the fx rail, not the legacy .sidebar, and starts as icons', async () => {
    await settle(<Sidebar />);
    expect(rail()).toHaveClass('fx-rail');
    expect(rail()).not.toHaveClass('sidebar');
    expect(rail()).not.toHaveAttribute('data-open');
  });

  it('opens on hover, waits 0.3 s after the pointer leaves, then folds', async () => {
    await settle(<Sidebar />);
    vi.useFakeTimers();
    fireEvent.pointerEnter(rail());
    expect(rail()).toHaveAttribute('data-open');
    fireEvent.pointerLeave(rail());
    act(() => {
      vi.advanceTimersByTime(299);
    });
    expect(rail()).toHaveAttribute('data-open');
    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(rail()).not.toHaveAttribute('data-open');
  });

  it('coming back before the wait ends keeps it open', async () => {
    await settle(<Sidebar />);
    vi.useFakeTimers();
    fireEvent.pointerEnter(rail());
    fireEvent.pointerLeave(rail());
    act(() => {
      vi.advanceTimersByTime(200);
    });
    fireEvent.pointerEnter(rail());
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(rail()).toHaveAttribute('data-open');
  });

  it('reads the wait from the "Wait before it folds to icons" setting', async () => {
    window.localStorage.setItem(FX_SETTINGS_STORAGE_KEY, JSON.stringify({ 'rail-wait': 1 }));
    await settle(<Sidebar />);
    vi.useFakeTimers();
    fireEvent.pointerEnter(rail());
    fireEvent.pointerLeave(rail());
    act(() => {
      vi.advanceTimersByTime(999);
    });
    expect(rail()).toHaveAttribute('data-open');
    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(rail()).not.toHaveAttribute('data-open');
  });

  it('pinned, it never folds, and the pin is remembered per browser', async () => {
    const view = await settle(<Sidebar />);
    fireEvent.pointerEnter(rail());
    fireEvent.click(screen.getByRole('button', { name: 'Pin side panel open' }));
    expect(rail()).toHaveAttribute('data-pinned');
    expect(window.localStorage.getItem(FX_RAIL_PIN_KEY)).toBe('1');
    vi.useFakeTimers();
    fireEvent.pointerLeave(rail());
    act(() => {
      vi.advanceTimersByTime(5000);
    });
    expect(rail()).toHaveAttribute('data-open');
    vi.useRealTimers();
    view.unmount();

    await settle(<Sidebar />);
    expect(rail()).toHaveAttribute('data-pinned');
    expect(rail()).toHaveAttribute('data-open');
    fireEvent.click(screen.getByRole('button', { name: 'Unpin side panel' }));
    expect(window.localStorage.getItem(FX_RAIL_PIN_KEY)).toBeNull();
  });

  it('keeps the pin out of the tab order while folded', async () => {
    await settle(<Sidebar />);
    expect(screen.getByRole('button', { name: 'Pin side panel open' })).toHaveAttribute(
      'tabindex',
      '-1',
    );
  });

  it('keyboard focus inside opens it', async () => {
    await settle(<Sidebar />);
    act(() => {
      screen.getByRole('link', { name: 'Users' }).focus();
    });
    expect(rail()).toHaveAttribute('data-open');
  });

  it('groups opened by hover stay open while the panel is open and fold with it', async () => {
    await settle(<Sidebar />);
    vi.useFakeTimers();
    const products = screen.getByRole('button', { name: 'Products' });
    const settings = screen.getByRole('button', { name: 'Settings' });
    fireEvent.pointerEnter(rail());
    fireEvent.pointerEnter(products.parentElement as Element);
    fireEvent.pointerEnter(settings.parentElement as Element);
    expect(products).toHaveAttribute('aria-expanded', 'true');
    expect(settings).toHaveAttribute('aria-expanded', 'true');
    fireEvent.pointerLeave(rail());
    act(() => {
      vi.advanceTimersByTime(300);
    });
    expect(products).toHaveAttribute('aria-expanded', 'false');
    expect(settings).toHaveAttribute('aria-expanded', 'false');
  });

  it('clicking a group pins it open; clicking again folds it', async () => {
    await settle(<Sidebar />);
    fireEvent.pointerEnter(rail());
    const products = screen.getByRole('button', { name: 'Products' });
    fireEvent.click(products);
    expect(products).toHaveAttribute('aria-expanded', 'true');
    fireEvent.click(products);
    expect(products).toHaveAttribute('aria-expanded', 'false');
  });

  it('gates entries exactly like the legacy menu and marks the current page', async () => {
    await settle(<Sidebar />);
    expect(screen.queryByText('Secret area')).toBeNull();
    expect(screen.getByRole('link', { name: 'Users' })).toHaveAttribute('aria-current', 'page');
  });
});

describe('top bar: one Jobs button', () => {
  it('replaces Uploads, Imports and Downloads, keeps Notifications, Chat and Apps', async () => {
    await settle(<Header />);
    expect(screen.getByRole('button', { name: 'Jobs, 6 running' })).toBeInTheDocument();
    for (const gone of ['Uploads', 'Imports', 'Downloads'])
      expect(screen.queryByRole('button', { name: gone })).toBeNull();
    for (const kept of ['Notifications', 'Chat', 'Apps', 'Theme', 'User menu'])
      expect(screen.getByRole('button', { name: kept })).toBeInTheDocument();
    expect(screen.getByText('6')).toBeInTheDocument();
  });

  it('shows no badge when nothing runs', async () => {
    counts = { uploads: 0, imports: 0, jobs: 0, downloads: 0 };
    await settle(<Header />);
    expect(screen.getByRole('button', { name: 'Jobs' })).toBeInTheDocument();
  });

  it('opens one sheet listing every kind; any opener opens it, closing clears them all', async () => {
    await settle(<Header />);
    fireEvent.click(screen.getByRole('button', { name: 'Jobs, 6 running' }));
    const sheet = await screen.findByRole('dialog', { name: 'Jobs' });
    // One list, no tabs (W3-JOBS); opening it also loads downloads.
    expect(within(sheet).queryByRole('tab')).toBeNull();
    expect(activity.uploads).toBe(true);
    expect(activity.downloads).toBe(true);

    // A storage migration starting while it is open keeps the one sheet.
    act(() => setFlag('jobs', true));
    expect(screen.getAllByRole('dialog', { name: 'Jobs' })).toHaveLength(1);

    fireEvent.keyDown(sheet, { key: 'Escape' });
    expect(Object.values(activity).some(Boolean)).toBe(false);
  });

  it('the old drawers render nothing while the switch is on', async () => {
    await settle(<JobsDrawer open onOpenChange={() => {}} jobs={[]} />);
    expect(screen.queryByRole('dialog')).toBeNull();
  });
});

function WithMain({ spec }: { spec: FxMainActionSpec }) {
  useRegisterMainAction(spec);
  return null;
}

const MAIN: FxMainActionSpec = { id: 'add', label: 'Add contact', onClick: () => {} };

describe('top bar: merging into the page header (wider screens)', () => {
  it('slides out after 64 px with search moved into the page header, back under 24 px', async () => {
    const { container } = await settle(
      <>
        <Header />
        <PageHeader title="Contacts" />
      </>,
    );
    const bar = container.querySelector('.fx-topbar') as HTMLElement;
    const slot = container.querySelector('[data-fx-header-merge]') as HTMLElement;
    const search = () => screen.getByRole('button', { name: 'Search' });
    expect(bar).not.toHaveAttribute('data-merged');
    expect(slot.contains(search())).toBe(false);

    setScroll(63);
    expect(bar).not.toHaveAttribute('data-merged');
    setScroll(64);
    expect(bar).toHaveAttribute('data-merged');
    expect(slot.contains(search())).toBe(true);

    setScroll(30);
    expect(bar).toHaveAttribute('data-merged');
    setScroll(23);
    expect(bar).not.toHaveAttribute('data-merged');
    expect(slot.contains(search())).toBe(false);
    expect(bar.contains(search())).toBe(true);
  });

  it('stays put with the merge setting off, or without a page header', async () => {
    window.localStorage.setItem(FX_SETTINGS_STORAGE_KEY, JSON.stringify({ merge: false }));
    const { container, unmount } = await settle(
      <>
        <Header />
        <PageHeader title="Contacts" />
      </>,
    );
    setScroll(400);
    expect(container.querySelector('.fx-topbar')).not.toHaveAttribute('data-merged');
    unmount();
    window.localStorage.clear();
    const second = await settle(<Header />);
    setScroll(400);
    expect(second.container.querySelector('.fx-topbar')).not.toHaveAttribute('data-merged');
  });
});

describe('top bar: phones (720px and narrower)', () => {
  beforeEach(() => {
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 375 });
    window.matchMedia = (query: string) =>
      ({
        matches: /max-width: (720|991)px/.test(query),
        media: query,
        onchange: null,
        addListener: () => {},
        removeListener: () => {},
        addEventListener: () => {},
        removeEventListener: () => {},
        dispatchEvent: () => false,
      }) as MediaQueryList;
    const real = HTMLElement.prototype.getBoundingClientRect;
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (
      this: HTMLElement,
    ) {
      if (this.hasAttribute('data-fx-header-actions'))
        return { bottom: 150 - window.scrollY } as DOMRect;
      if (this.classList.contains('fx-topbar')) return { bottom: 60 } as DOMRect;
      return real.call(this);
    });
  });

  it('condenses once the red button is under the bar, with the red action floating in', async () => {
    const { container } = await settle(
      <>
        <Header />
        <PageHeader title="Contacts" />
        <WithMain spec={MAIN} />
      </>,
    );
    const bar = container.querySelector('.fx-topbar') as HTMLElement;
    setScroll(0);
    expect(bar).not.toHaveAttribute('data-condensed');
    expect(document.querySelector('[data-fx-floating-action]')).toBeNull();
    // The phone keeps its own bar: it never merges.
    setScroll(100);
    expect(bar).not.toHaveAttribute('data-merged');
    expect(bar).toHaveAttribute('data-condensed');
    const floating = document.querySelector('[data-fx-floating-action]') as HTMLElement;
    expect(within(floating).getByRole('button', { name: 'Add contact' })).toBeInTheDocument();

    // The icon buttons fold into one; tapping it opens them back up.
    const more = screen.getByRole('button', { name: 'Show the top bar buttons' });
    fireEvent.click(more);
    expect(screen.queryByRole('button', { name: 'Show the top bar buttons' })).toBeNull();

    setScroll(0);
    expect(bar).not.toHaveAttribute('data-condensed');
    expect(document.querySelector('[data-fx-floating-action]')).toBeNull();
  });

  it('no floating red action with that setting off', async () => {
    window.localStorage.setItem(FX_SETTINGS_STORAGE_KEY, JSON.stringify({ 'float-act': false }));
    await settle(
      <>
        <Header />
        <PageHeader title="Contacts" />
        <WithMain spec={MAIN} />
      </>,
    );
    setScroll(100);
    expect(document.querySelector('[data-fx-floating-action]')).toBeNull();
  });
});

describe('Theme panel', () => {
  it('stays open when the top bar is swapped (the switch was just turned on)', async () => {
    const first = await settle(<ThemeButton />);
    fireEvent.click(screen.getByRole('button', { name: 'Theme' }));
    expect(await screen.findByRole('dialog', { name: 'Theme' })).toBeInTheDocument();
    first.unmount();
    await settle(<ThemeButton />);
    expect(screen.getByRole('dialog', { name: 'Theme' })).toBeInTheDocument();
  });
});
