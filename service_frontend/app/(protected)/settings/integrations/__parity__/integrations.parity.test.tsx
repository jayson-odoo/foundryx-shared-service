/**
 * Switch-off parity for the integrations pages (Foundryx UIUX, slice
 * W4-TEMPLATES). Recorded on the code BEFORE the slice changed anything, so a
 * later change that alters what a user sees or what reaches the backend with
 * the switch off fails here. A change that needs one of these snapshots
 * updated is wrong by definition: fix the code, never the snapshot.
 *
 * Covers: the integrations list, a connection record (read, edit with its
 * write-only secrets, Test connection, the targeted test, Save) and the new
 * connection form (provider deep link, Create).
 */
import type { ReactElement } from 'react';
import { fireEvent, render as rtlRender, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { SettingsProvider } from '@/providers/settings-provider';
import { answers, calls, connection, parityHtml, resetCalls, settle } from './integration-test-kit';

const h = vi.hoisted(() => ({
  params: { id: 'con-1' } as Record<string, string>,
  search: new URLSearchParams(),
  pathname: '/settings/integrations',
}));

vi.mock('@/lib/toast', async () => (await import('./integration-test-kit')).toastMock);
vi.mock('@/services/integration-service', async () => (await import('./integration-test-kit')).integrationServiceMock);
vi.mock('@/services/pending-actions-service', async () => (await import('./integration-test-kit')).pendingActionsServiceMock);
vi.mock('@/services/preferences-service', async () => (await import('./integration-test-kit')).preferencesServiceMock);

vi.mock('next/navigation', async () => {
  const kit = await import('./integration-test-kit');
  const router = {
    push: (...args: unknown[]) => kit.calls.push(['router.push', ...args]),
    replace: (...args: unknown[]) => kit.calls.push(['router.replace', ...args]),
    prefetch: () => undefined,
    back: () => undefined,
    refresh: () => undefined,
  };
  return {
    useRouter: () => router,
    usePathname: () => h.pathname,
    useSearchParams: () => h.search,
    useParams: () => h.params,
  };
});

vi.mock('next-auth/react', () => ({
  useSession: () => ({
    data: { user: { name: 'Kay Tan', timezone: 'Asia/Kuala_Lumpur', permissions: [] } },
    status: 'authenticated',
  }),
  getSession: () => Promise.resolve(null),
  signOut: () => undefined,
}));

vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({ can: () => true, ready: true, permissions: new Set<string>() }),
}));

vi.mock('@/components/common/require-permission', () => ({
  RequirePermission: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock('@/lib/impersonation-store', () => ({ useImpersonationSession: () => null }));
vi.mock('@/services/terminology-service', () => ({
  terminologyService: { getTerminology: () => Promise.resolve({}) },
}));
vi.mock('@/providers/import-activity-provider', () => ({
  useImportActivity: () => ({ openImport: () => undefined }),
}));

// Imported after the mocks.
import IntegrationsPage from '../page';
import NewConnectionPage from '../new/page';
import ConnectionFormPage from '../[id]/page';

function render(ui: ReactElement) {
  return rtlRender(<SettingsProvider>{ui}</SettingsProvider>);
}

beforeEach(() => {
  resetCalls();
  answers.connection = connection();
  answers.testOk = true;
  answers.createFails = false;
  h.params = { id: 'con-1' };
  h.search = new URLSearchParams();
  h.pathname = '/settings/integrations';
  window.localStorage.clear();
});

describe('integrations list (switch off)', () => {
  it('renders the list as today', async () => {
    const { container } = render(<IntegrationsPage />);
    await screen.findByText('Company mail');
    await settle();
    expect(parityHtml(container)).toMatchSnapshot();
  });
});

describe('connection record (switch off)', () => {
  beforeEach(() => {
    h.pathname = '/settings/integrations/con-1';
  });

  it('renders read mode and runs Test connection and the targeted test as today', async () => {
    const { container } = render(<ConnectionFormPage />);
    await screen.findByText('smtp.maju.my');
    await settle();
    expect(parityHtml(container)).toMatchSnapshot('read');

    // The gear menu's Test connection.
    fireEvent.pointerDown(screen.getByRole('button', { name: /actions|more|settings/i }), { button: 0 });
    await settle();
    const testItem = await screen.findByRole('menuitem', { name: /Test connection/ });
    fireEvent.click(testItem);
    await settle();

    // The targeted test (Send test email) with an address.
    fireEvent.change(screen.getByPlaceholderText('you@example.com'), { target: { value: ' ops@maju.my ' } });
    answers.testOk = false;
    fireEvent.click(screen.getByRole('button', { name: /Send test email/ }));
    await settle();
    expect(calls.filter((c) => c[0] !== 'integration.get')).toMatchSnapshot('calls');
  });

  it('renders edit mode with write-only secrets and saves as today', async () => {
    h.search = new URLSearchParams('edit=1');
    const { container } = render(<ConnectionFormPage />);
    await screen.findByDisplayValue('smtp.maju.my');
    await settle();
    expect(parityHtml(container)).toMatchSnapshot('edit');

    fireEvent.change(screen.getByDisplayValue('Company mail'), { target: { value: 'Company mail 2' } });
    fireEvent.change(screen.getByDisplayValue('smtp.maju.my'), { target: { value: 'mail.maju.my' } });
    fireEvent.click(screen.getByRole('button', { name: /^Save/ }));
    await settle();
    expect(calls.filter((c) => c[0] !== 'integration.get')).toMatchSnapshot('save calls');
    expect(parityHtml(container)).toMatchSnapshot('after save');
  });
});

describe('new connection (switch off)', () => {
  beforeEach(() => {
    h.pathname = '/settings/integrations/new';
  });

  it('renders the provider-picked form and creates as today', async () => {
    h.search = new URLSearchParams('provider=smtp');
    const { container } = render(<NewConnectionPage />);
    await screen.findByPlaceholderText('smtp.example.com');
    await settle();
    expect(parityHtml(container)).toMatchSnapshot('form');

    fireEvent.change(screen.getByPlaceholderText('smtp.example.com'), { target: { value: 'smtp.maju.my' } });
    const inputs = container.querySelectorAll('input');
    const byName = (n: string) => Array.from(inputs).find((i) => i.getAttribute('name') === n) as HTMLInputElement;
    fireEvent.change(byName('config.username'), { target: { value: 'mailer' } });
    fireEvent.change(byName('credentials.password'), { target: { value: 'pw-123456' } });
    fireEvent.change(byName('config.fromEmail'), { target: { value: 'hello@maju.my' } });
    fireEvent.click(screen.getByRole('button', { name: /^Save|^Create/ }));
    await settle();
    expect(calls).toMatchSnapshot('create calls');
  });
});
