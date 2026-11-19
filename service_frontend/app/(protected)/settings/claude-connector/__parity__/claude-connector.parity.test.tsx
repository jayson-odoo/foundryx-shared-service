/**
 * Switch-off parity for the Claude connector pages (see
 * components/fx/__parity__/parity-utils.ts). Recorded on the code before the
 * W4-AI slice: the grants list, the Products and Access tabs, a grant
 * record, and the product settings form (read, editing, secrets, new),
 * rendered with the Foundryx UIUX switch off. A change that needs one of
 * these snapshots updated changes what a user sees today: fix the code,
 * never the snapshot.
 */
import type { ReactElement } from 'react';
import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { parityHtml } from '@/components/fx/__parity__/parity-utils';
import ClaudeConnectorPage from '../page';
import { GrantDetailView } from '../components/grant-detail-view';
import { ProductFormView } from '../components/product-form-view';
import { Look, writes } from './cc-kit';

/**
 * React 19 ids (`_r_7f_`) renamed in order of first appearance, and the
 * mid-animation inline style a closing Radix tab panel may still carry
 * dropped (it depends on timing, not on the markup).
 */
function maskIds(html: string): string {
  const seen = new Map<string, string>();
  const still = html.replace(/ style="animation-duration: 0s;"/g, ' style=""');
  return still.replace(/_r_[0-9a-z]+_/g, (id) => {
    let stable = seen.get(id);
    if (!stable) {
      stable = `_rid${seen.size}_`;
      seen.set(id, stable);
    }
    return stable;
  });
}

const nav = vi.hoisted(() => ({ path: '/settings/claude-connector' }));
const perms = vi.hoisted(() => [
  'connector.read',
  'connector.manage',
  'connector.settings',
  'app_store.read',
]);

vi.mock('next/navigation', () => ({
  usePathname: vi.fn(() => nav.path),
  useSearchParams: vi.fn(() => new URLSearchParams()),
  useParams: vi.fn(() => ({})),
  useRouter: vi.fn(() => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn(), back: vi.fn() })),
  notFound: vi.fn(() => {
    throw new Error('NEXT_NOT_FOUND');
  }),
}));
vi.mock('next-auth/react', () => ({
  useSession: () => ({
    data: { user: { id: 'me', name: 'Demo Admin', permissions: perms } },
    status: 'authenticated',
  }),
}));
vi.mock('next-themes', () => ({
  useTheme: () => ({ theme: 'light', setTheme: vi.fn() }),
}));
vi.mock('@/lib/impersonation-store', () => ({
  useImpersonationSession: () => null,
}));
vi.mock('@/services/terminology-service', () => ({
  terminologyService: { getTerminology: vi.fn().mockResolvedValue({}) },
}));
vi.mock('@/providers/settings-provider', () => ({
  useSettings: () => ({ settings: { container: 'fixed' } }),
}));
vi.mock('@/hooks/use-deferred-action', () => ({
  useDeferredAction: () => ({ state: { status: 'idle' }, start: vi.fn(async () => ({})), cancel: vi.fn() }),
}));
vi.mock('@/lib/api-client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api-client')>();
  const kit = await import('./cc-kit');
  return {
    ...actual,
    apiFetch: vi.fn(kit.fakeApiFetch),
    apiFetchText: vi.fn(async () => ''),
  };
});

afterEach(() => {
  writes.length = 0;
  document.body.innerHTML = '';
});

type Ui = ReturnType<typeof userEvent.setup>;

async function snapOff(
  path: string,
  ui: ReactElement,
  ready: (root: HTMLElement) => boolean,
  steps?: (u: Ui) => Promise<void>,
  readyAfter?: (root: HTMLElement) => boolean,
) {
  nav.path = path;
  const u = userEvent.setup();
  let utils!: ReturnType<typeof render>;
  await act(async () => {
    utils = render(<Look fx={false}>{ui}</Look>);
  });
  await waitFor(() => expect(ready(utils.container)).toBe(true));
  if (steps) {
    await steps(u);
    if (readyAfter) await waitFor(() => expect(readyAfter(utils.container)).toBe(true));
  }
  await act(async () => {
    await new Promise((r) => setTimeout(r, 0));
  });
  const html = maskIds(parityHtml(utils.container));
  utils.unmount();
  return html;
}

const hasText = (text: string) => (root: HTMLElement) => root.textContent?.includes(text) ?? false;

describe('Claude connector switch-off parity', () => {
  it('grants tab (with the access tab kept mounted)', async () => {
    expect(
      await snapOff('/settings/claude-connector', <ClaudeConnectorPage />, (r) =>
        hasText('Lim Wei Jie')(r) && hasText('Recent changes')(r),
      ),
    ).toMatchSnapshot();
  });

  it('products tab', async () => {
    expect(
      await snapOff(
        '/settings/claude-connector',
        <ClaudeConnectorPage />,
        hasText('Lim Wei Jie'),
        async (u) => {
          await u.click(screen.getByRole('tab', { name: 'Products' }));
        },
        hasText('Refresh manifest'),
      ),
    ).toMatchSnapshot();
  });

  it('access tab, editing', async () => {
    expect(
      await snapOff(
        '/settings/claude-connector',
        <ClaudeConnectorPage />,
        hasText('Recent changes'),
        async (u) => {
          await u.click(screen.getByRole('tab', { name: 'Access' }));
          await u.click(screen.getByRole('button', { name: 'Edit' }));
        },
        hasText('Save settings'),
      ),
    ).toMatchSnapshot();
  });

  it('grant record', async () => {
    expect(
      await snapOff('/settings/claude-connector/g-1', <GrantDetailView grantId="g-1" />, hasText('crm-user-42')),
    ).toMatchSnapshot();
  });

  it('product settings, read', async () => {
    expect(
      await snapOff(
        '/settings/claude-connector/products/sorento',
        <ProductFormView productKey="sorento" initialEditing={false} />,
        hasText('conn-sorento'),
      ),
    ).toMatchSnapshot();
  });

  it('product settings, secrets tab read', async () => {
    expect(
      await snapOff(
        '/settings/claude-connector/products/sorento',
        <ProductFormView productKey="sorento" initialEditing={false} />,
        hasText('conn-sorento'),
        async (u) => {
          await u.click(screen.getByRole('tab', { name: 'Secrets' }));
        },
        hasText('Secret from product'),
      ),
    ).toMatchSnapshot();
  });

  it('product settings, secrets tab editing', async () => {
    expect(
      await snapOff(
        '/settings/claude-connector/products/sorento',
        <ProductFormView productKey="sorento" initialEditing />,
        (r) => r.querySelector('input') !== null,
        async (u) => {
          await u.click(screen.getByRole('tab', { name: 'Secrets' }));
        },
        hasText('Remove the saved secret'),
      ),
    ).toMatchSnapshot();
  });

  it('new product', async () => {
    expect(
      await snapOff(
        '/settings/claude-connector/products/new',
        <ProductFormView initialEditing />,
        hasText('New product'),
      ),
    ).toMatchSnapshot();
  });
});
