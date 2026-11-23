/**
 * System banners, the lost-connection banner, the impersonation banner and
 * the blocked-area strip with the Foundryx UIUX switch on (slice F5).
 */
import { useMemo, type ReactNode } from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { FX_DEFAULT_THEME } from '@/lib/fx/cookies';
import { FxProvider } from '@/providers/fx-provider';
import { ImpersonationBanner } from '@/components/impersonation/impersonation-banner';
import {
  FX_BANNERS_CLOSED_KEY,
  orderBanners,
  resetSystemBannersForTests,
  useSystemBanner,
  type FxBanner,
} from './banner-store';
import { FxBlockedArea } from './blocked-area';
import { FxSystemBannerHost } from './system-banner';
import {
  FX_CONNECTION_BANNER_DELAY_MS,
  FX_CONNECTION_BANNER_TEXT,
  useConnectionBanner,
} from './use-connection-banner';

vi.mock('next/navigation', () => ({
  usePathname: () => '/',
  useRouter: () => ({ push: vi.fn(), prefetch: vi.fn(), refresh: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

const impersonation = vi.hoisted(() => ({
  session: null as null | {
    targetUser: { id: string; name: string; email: string };
  },
  stop: vi.fn(async () => {}),
}));

vi.mock('@/hooks/use-impersonation', () => ({
  useImpersonation: () => ({
    session: impersonation.session,
    stop: impersonation.stop,
    hydrate: async () => {},
    pending: false,
  }),
}));

function On({ children }: { children: ReactNode }) {
  return (
    <FxProvider initial initialTheme={FX_DEFAULT_THEME}>
      {children}
    </FxProvider>
  );
}

function Banner({ banner }: { banner: FxBanner }) {
  const stable = useMemo(() => banner, [banner]);
  useSystemBanner(stable);
  return null;
}

const NEWS: FxBanner = {
  id: 'news-maintenance',
  tone: 'info',
  text: 'Maintenance on Sat 8 Nov, 11 pm to 1 am. Save your work before then.',
  closable: true,
};
const WARN: FxBanner = {
  id: 'trial',
  tone: 'warn',
  text: 'Your trial ends on 30 Nov.',
  action: { label: 'Details', href: '/settings/general' },
};

beforeEach(() => {
  window.localStorage.clear();
  resetSystemBannersForTests();
  impersonation.session = null;
});

afterEach(() => {
  vi.useRealTimers();
  document.documentElement.style.removeProperty('--shell-top-offset');
});

describe('banner order', () => {
  it('puts warn before info, keeps arrival order within each, and drops closed news', () => {
    const info2 = { ...NEWS, id: 'info-2', text: 'b' };
    const warn2 = { ...WARN, id: 'warn-2' };
    expect(
      orderBanners([NEWS, WARN, info2, warn2], new Set()).map((b) => b.id),
    ).toEqual(['trial', 'warn-2', 'news-maintenance', 'info-2']);
    expect(
      orderBanners([NEWS, WARN], new Set(['news-maintenance'])).map((b) => b.id),
    ).toEqual(['trial']);
    // Only news can be closed: a banner about something true stays.
    expect(orderBanners([WARN], new Set(['trial'])).map((b) => b.id)).toEqual([
      'trial',
    ]);
  });
});

describe('system banner bar', () => {
  it('shows the most urgent first with "1 of 2" and steps through them', async () => {
    await act(async () => {
      render(
        <On>
          <FxSystemBannerHost />
          <Banner banner={NEWS} />
          <Banner banner={WARN} />
        </On>,
      );
    });
    expect(screen.getByText('Your trial ends on 30 Nov.')).toBeInTheDocument();
    expect(screen.getByText('1 of 2')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Details' })).toHaveAttribute(
      'href',
      '/settings/general',
    );
    // A banner about something still true has no close.
    expect(screen.queryByRole('button', { name: 'Close' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Next message' }));
    expect(screen.getByText(NEWS.text as string)).toBeInTheDocument();
    expect(screen.getByText('2 of 2')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Previous message' }));
    expect(screen.getByText('1 of 2')).toBeInTheDocument();
  });

  it('closes news for good (this browser)', async () => {
    const first = render(
      <On>
        <FxSystemBannerHost />
        <Banner banner={NEWS} />
      </On>,
    );
    await act(async () => {});
    fireEvent.click(screen.getByRole('button', { name: 'Close' }));
    expect(JSON.parse(window.localStorage.getItem(FX_BANNERS_CLOSED_KEY) ?? '[]')).toEqual([
      'news-maintenance',
    ]);
    first.unmount();
    resetSystemBannersForTests();
    await act(async () => {
      render(
        <On>
          <FxSystemBannerHost />
          <Banner banner={NEWS} />
        </On>,
      );
    });
    expect(screen.queryByText(NEWS.text as string)).toBeNull();
  });

  it('pushes the shell down by its real height, and back to 0 when it goes', async () => {
    const spy = vi
      .spyOn(HTMLElement.prototype, 'offsetHeight', 'get')
      .mockReturnValue(32);
    const view = render(
      <On>
        <FxSystemBannerHost />
        <Banner banner={WARN} />
      </On>,
    );
    await act(async () => {});
    const root = document.documentElement.style;
    expect(root.getPropertyValue('--shell-top-offset')).toBe('32px');
    view.rerender(
      <On>
        <FxSystemBannerHost />
      </On>,
    );
    await act(async () => {});
    expect(root.getPropertyValue('--shell-top-offset')).toBe('0px');
    spy.mockRestore();
  });

  it('shows nothing with no banner', async () => {
    const { container } = render(
      <On>
        <FxSystemBannerHost />
      </On>,
    );
    await act(async () => {});
    expect(container.querySelector('[data-fx-banner]')).toBeNull();
  });
});

function Feed({ connected }: { connected: boolean }) {
  const showing = useConnectionBanner(connected);
  return <span data-testid="showing">{String(showing)}</span>;
}

describe('connection banner', () => {
  it('shows only after 5 s without the connection, and leaves once it is back', async () => {
    vi.useFakeTimers();
    const view = render(
      <On>
        <FxSystemBannerHost />
        <Feed connected={false} />
      </On>,
    );
    await act(async () => {});
    act(() => {
      vi.advanceTimersByTime(FX_CONNECTION_BANNER_DELAY_MS - 1);
    });
    expect(FX_CONNECTION_BANNER_DELAY_MS).toBe(5000);
    expect(screen.queryByText(FX_CONNECTION_BANNER_TEXT)).toBeNull();
    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(screen.getByText(FX_CONNECTION_BANNER_TEXT)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Close' })).toBeNull();

    view.rerender(
      <On>
        <FxSystemBannerHost />
        <Feed connected />
      </On>,
    );
    act(() => {
      vi.advanceTimersByTime(400);
    });
    expect(screen.queryByText(FX_CONNECTION_BANNER_TEXT)).toBeNull();
    expect(screen.getByTestId('showing')).toHaveTextContent('false');
  });

  it('a short drop that fixes itself never shows it', async () => {
    vi.useFakeTimers();
    const view = render(
      <On>
        <FxSystemBannerHost />
        <Feed connected={false} />
      </On>,
    );
    await act(async () => {});
    act(() => {
      vi.advanceTimersByTime(3000);
    });
    view.rerender(
      <On>
        <FxSystemBannerHost />
        <Feed connected />
      </On>,
    );
    act(() => {
      vi.advanceTimersByTime(10000);
    });
    expect(screen.queryByText(FX_CONNECTION_BANNER_TEXT)).toBeNull();
  });

  it('does nothing with the switch off', () => {
    vi.useFakeTimers();
    render(<Feed connected={false} />);
    act(() => {
      vi.advanceTimersByTime(10000);
    });
    expect(screen.getByTestId('showing')).toHaveTextContent('false');
  });
});

describe('impersonation banner (switch on)', () => {
  beforeEach(() => {
    impersonation.session = {
      targetUser: { id: 'u-9', name: 'Tan Mei Ling', email: 'tan@example.com' },
    };
  });

  it('is a warn system banner with one text button and SS\'s "Hide banner"', async () => {
    await act(async () => {
      render(
        <On>
          <FxSystemBannerHost />
          <ImpersonationBanner />
        </On>,
      );
    });
    const bar = document.querySelector('[data-fx-banner="warn"]') as HTMLElement;
    expect(bar).toHaveTextContent(
      'Viewing as Tan Mei Ling. Anything you create or change is still recorded under your own account.',
    );
    expect(screen.getByRole('link', { name: 'Tan Mei Ling' })).toHaveAttribute(
      'href',
      '/user-management/users/u-9',
    );
    expect(
      screen.getByRole('button', { name: 'Stop viewing as Tan Mei Ling' }),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Hide banner' }));
    expect(window.localStorage.getItem('foundryx.impersonation.collapsed')).toBe('1');
    expect(screen.getByRole('button', { name: /Viewing as Tan Mei Ling/ })).toHaveAttribute(
      'title',
      'Show impersonation banner',
    );
    fireEvent.click(screen.getByRole('button', { name: /Viewing as Tan Mei Ling/ }));
    expect(
      screen.getByRole('button', { name: 'Stop viewing as Tan Mei Ling' }),
    ).toBeInTheDocument();
  });

  it('stops viewing through the same session call', async () => {
    const reload = vi.fn();
    vi.stubGlobal('location', { ...window.location, reload });
    await act(async () => {
      render(
        <On>
          <FxSystemBannerHost />
          <ImpersonationBanner />
        </On>,
      );
    });
    await act(async () => {
      fireEvent.click(
        screen.getByRole('button', { name: 'Stop viewing as Tan Mei Ling' }),
      );
    });
    expect(impersonation.stop).toHaveBeenCalled();
    vi.unstubAllGlobals();
  });
});

describe('blocked area strip', () => {
  it('says what is missing with the one way to fix it', () => {
    const onClick = vi.fn();
    render(
      <FxBlockedArea action={{ label: 'Connect channel', onClick }}>
        No channel is connected to this workspace.
      </FxBlockedArea>,
    );
    expect(screen.getByRole('status')).toHaveTextContent(
      'No channel is connected to this workspace.',
    );
    fireEvent.click(screen.getByRole('button', { name: 'Connect channel' }));
    expect(onClick).toHaveBeenCalled();
  });
});
