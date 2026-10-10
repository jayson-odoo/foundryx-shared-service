import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render as rtlRender, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SettingsProvider } from '@/providers/settings-provider';
import { TooltipsProvider } from '@/providers/tooltips-provider';
import { ProductFormView } from './product-form-view';

/** Container reads layout settings - provide the real providers. */
function render(ui: React.ReactElement) {
  return rtlRender(
    <SettingsProvider>
      <TooltipsProvider>{ui}</TooltipsProvider>
    </SettingsProvider>,
  );
}

const canKeys: string[] = ['connector.read', 'connector.settings'];
vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({ can: (k: string) => canKeys.includes(k), ready: true, permissions: new Set(canKeys) }),
}));
const getProductSettings = vi.fn();
const updateProductSettings = vi.fn();
const createProduct = vi.fn();
const deleteProduct = vi.fn();
vi.mock('@/services/connector-service', () => ({
  getProductSettings: (...a: unknown[]) => getProductSettings(...a),
  updateProductSettings: (...a: unknown[]) => updateProductSettings(...a),
  createProduct: (...a: unknown[]) => createProduct(...a),
  deleteProduct: (...a: unknown[]) => deleteProduct(...a),
}));
const push = vi.fn();
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push, replace: vi.fn(), back: vi.fn() }),
  usePathname: () => '/settings/claude-connector/products/acme',
  useSearchParams: () => new URLSearchParams(),
  useParams: () => ({ key: 'acme' }),
}));
vi.mock('@/hooks/use-datetime', () => ({
  useDatetime: () => ({ formatDate: (s: string) => s, formatDateTime: (s: string) => s }),
}));
vi.mock('next-auth/react', () => ({ useSession: () => ({ data: null, status: 'unauthenticated' }), signOut: vi.fn() }));
vi.mock('@/services/terminology-service', () => ({ terminologyService: { getTerminology: vi.fn().mockResolvedValue({}), list: vi.fn().mockResolvedValue([]), get: vi.fn().mockResolvedValue({}) } }));
vi.mock('@/lib/toast', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const v = (value: string | null, source: string) => ({ value, source });
const acme = (over: Record<string, unknown> = {}) => ({
  key: 'acme',
  stored: false,
  status: 'ok',
  fields: {
    displayName: v('Acme', 'environment'),
    connectionId: v('conn-acme', 'environment'),
    consentUrl: v('https://acme.test/connect/claude', 'environment'),
    apiBaseUrl: v('https://acme.test', 'environment'),
    issuer: v('acme', 'default'),
    consentAudience: v('acme-connector-consent', 'default'),
    callAudience: v('acme-connector-api', 'default'),
  },
  secrets: {
    ssToProduct: { state: 'set', source: 'environment' },
    productToSs: { state: 'unreadable', source: 'unreadable' },
  },
  ...over,
});

beforeEach(() => {
  vi.clearAllMocks();
  canKeys.splice(0, canKeys.length, 'connector.read', 'connector.settings');
  getProductSettings.mockResolvedValue(acme());
});

describe('ProductFormView (SETTINGS-IN-DB-SS)', () => {
  it('read mode shows values, their source, and secret state only', async () => {
    render(<ProductFormView productKey="acme" initialEditing={false} />);
    await screen.findByText('https://acme.test/connect/claude');
    expect(screen.getAllByText('Environment').length).toBeGreaterThan(0);
    await userEvent.click(screen.getByRole('tab', { name: /secrets/i }));
    expect(screen.getByText('Set')).toBeTruthy();
    expect(screen.getByText('Unreadable - re-enter')).toBeTruthy();
    expect(screen.queryAllByRole('textbox').length).toBe(0);
  });

  it('edit of an environment product sends only the changed field and blank-kept secrets', async () => {
    updateProductSettings.mockResolvedValue(
      acme({ stored: true, fields: { ...acme().fields, displayName: v('Acme Prod', 'database') } }),
    );
    render(<ProductFormView productKey="acme" initialEditing />);
    const name = await screen.findByLabelText('Display name');
    expect((name as HTMLInputElement).value).toBe('');
    expect((name as HTMLInputElement).placeholder).toBe('Acme');
    await userEvent.type(name, 'Acme Prod');
    await userEvent.click(screen.getByRole('button', { name: /^save/i }));
    await waitFor(() => expect(updateProductSettings).toHaveBeenCalled());
    const [key, body] = updateProductSettings.mock.calls[0];
    expect(key).toBe('acme');
    expect(body.displayName).toBe('Acme Prod');
    expect(body.consentUrl).toBe('');
    expect(body).not.toHaveProperty('ssToProductSecret');
    expect(body).not.toHaveProperty('key');
  });

  it('read-only permission: no Edit toggle', async () => {
    canKeys.splice(0, canKeys.length, 'connector.read');
    render(<ProductFormView productKey="acme" initialEditing={false} />);
    await screen.findByText('https://acme.test/connect/claude');
    expect(screen.queryByRole('button', { name: /^edit$/i })).toBeNull();
  });

  it('create posts the key + values and opens the saved product', async () => {
    createProduct.mockResolvedValue(acme({ key: 'delta', stored: true }));
    render(<ProductFormView initialEditing />);
    await userEvent.type(await screen.findByLabelText('Key'), 'delta');
    await userEvent.type(screen.getByLabelText('Connection ID'), 'conn-delta');
    await userEvent.click(screen.getByRole('button', { name: /^create/i }));
    await waitFor(() => expect(createProduct).toHaveBeenCalled());
    expect(createProduct.mock.calls[0][0]).toMatchObject({ key: 'delta', connectionId: 'conn-delta' });
    expect(push).toHaveBeenCalledWith('/settings/claude-connector/products/delta');
  });

  it('not found shows a way back, not a spinner', async () => {
    getProductSettings.mockRejectedValue(new Error('404'));
    render(<ProductFormView productKey="nope" initialEditing={false} />);
    await screen.findByText('Product not found.');
  });
});
