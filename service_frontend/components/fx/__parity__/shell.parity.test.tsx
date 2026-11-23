/**
 * Switch-off parity: the demo1 top bar (`Header`, desktop and phone width) and
 * the side panel (`Sidebar`) (see parity-utils.ts). Data hooks are stubbed;
 * every presentational child renders for real.
 */
import { act, render } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Header } from '@/app/components/layouts/demo1/components/header';
import { Sidebar } from '@/app/components/layouts/demo1/components/sidebar';
import { parityHtml } from './parity-utils';

vi.mock('next/navigation', () => ({
  usePathname: () => '/user-management/users',
  useRouter: () => ({ push: vi.fn(), prefetch: vi.fn(), replace: vi.fn() }),
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
  useTheme: () => ({
    theme: 'light',
    setTheme: vi.fn(),
    resolvedTheme: 'light',
  }),
}));

vi.mock('@/hooks/use-app-store', () => ({
  useInstalledModules: () => ({ ready: true, isActive: () => true }),
}));

vi.mock('@/hooks/use-terminology', () => ({
  useTerminology: () => ({
    labelPlural: (k: string) => k,
    label: (k: string) => k,
  }),
}));

vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({
    can: () => true,
    ready: true,
    permissions: new Set<string>(),
  }),
}));

vi.mock('@/config/menu.config', () => ({
  MENU_SIDEBAR: [
    { title: 'Users', path: '/user-management/users' },
    { title: 'Roles', path: '/user-management/roles' },
  ],
  MENU_MEGA: [{ title: 'Home', path: '/' }],
  MENU_MEGA_MOBILE: [{ title: 'Home', path: '/' }],
}));

vi.mock('@/providers/import-activity-provider', () => ({
  useImportActivity: () => ({
    activeCount: 0,
    setDrawerOpen: vi.fn(),
    openImport: vi.fn(),
  }),
}));

vi.mock('@/providers/jobs-activity-provider', () => ({
  useJobsActivity: () => ({ activeCount: 0, setDrawerOpen: vi.fn() }),
}));

vi.mock('@/components/platform/document-drive/upload-manager', () => ({
  useUploadManager: () => ({ activeCount: 0, setOpen: vi.fn() }),
}));

vi.mock('@/components/platform/document-drive/downloads-manager', () => ({
  useDownloads: () => ({ activeCount: 0, setOpen: vi.fn() }),
}));

vi.mock('@/providers/settings-provider', () => ({
  useSettings: () => ({
    settings: {
      layouts: { demo1: { sidebarTheme: 'light', sidebarCollapse: false } },
    },
    storeOption: vi.fn(),
    setOption: vi.fn(),
  }),
}));

const desktopWidth = window.innerWidth;

afterEach(() => {
  Object.defineProperty(window, 'innerWidth', {
    configurable: true,
    value: desktopWidth,
  });
});

describe('parity (switch off): Header', () => {
  it('desktop top bar renders as before', async () => {
    Object.defineProperty(window, 'innerWidth', {
      configurable: true,
      value: 1280,
    });
    let container!: HTMLElement;
    await act(async () => {
      ({ container } = render(<Header />));
    });
    expect(parityHtml(container)).toMatchSnapshot();
  });

  it('phone top bar (375px) renders as before', async () => {
    Object.defineProperty(window, 'innerWidth', {
      configurable: true,
      value: 375,
    });
    let container!: HTMLElement;
    await act(async () => {
      ({ container } = render(<Header />));
    });
    expect(parityHtml(container)).toMatchSnapshot();
  });
});

describe('parity (switch off): Sidebar', () => {
  it('side panel renders as before', async () => {
    let container!: HTMLElement;
    await act(async () => {
      ({ container } = render(<Sidebar />));
    });
    expect(parityHtml(container)).toMatchSnapshot();
  });
});
