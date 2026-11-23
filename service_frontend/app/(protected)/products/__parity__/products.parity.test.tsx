/**
 * Switch-off parity for the Products page (Foundryx UIUX slice W1-PRODUCTS,
 * build plan 1.3 and 4): the page (list with rows) and the product dialog
 * (add, edit, edit of a software product) rendered with the switch OFF.
 * Recorded on the code as it was before the slice; a change that needs one of
 * these snapshots updated is wrong by definition (fix the code, never the
 * snapshot). Generated ids are renamed in order of appearance.
 */
import { render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { parityHtml } from '@/components/fx/__parity__/parity-utils';
import { SettingsProvider } from '@/providers/settings-provider';
import type { Product, ProductKind } from '@/services/productService';
import ProductsPage from '../page';
import { ProductFormDialog } from '../product-form-dialog';

vi.mock('next/navigation', () => ({
  useRouter: vi.fn(() => ({ push: vi.fn(), prefetch: vi.fn(), replace: vi.fn(), back: vi.fn() })),
  useSearchParams: vi.fn(() => new URLSearchParams()),
  usePathname: vi.fn(() => '/products'),
}));

vi.mock('next-auth/react', () => ({
  useSession: () => ({
    data: {
      user: {
        name: 'Demo Admin',
        permissions: ['products.read', 'products.create', 'products.update', 'products.delete'],
      },
    },
    status: 'authenticated',
  }),
}));

vi.mock('@/lib/impersonation-store', () => ({
  useImpersonationSession: () => null,
}));

vi.mock('@/services/preferences-service', () => ({
  preferencesService: {
    get: vi.fn().mockResolvedValue(null),
    save: vi.fn().mockResolvedValue(undefined),
  },
}));

vi.mock('@/services/terminology-service', () => ({
  terminologyService: { getTerminology: vi.fn().mockResolvedValue({}) },
}));

vi.mock('@/providers/import-activity-provider', () => ({
  useImportActivity: () => ({ openImport: vi.fn() }),
}));

const product = (over: Partial<Product>): Product => ({
  id: 'p1',
  categoryId: null,
  name: 'Barcode scanner',
  sku: 'HW-SCAN-01',
  kind: 'goods',
  kindLabel: 'Goods',
  defaultPrice: 189,
  tax: 8,
  currency: 'MYR',
  uom: 'unit',
  isActive: true,
  createdAt: '2026-11-01T02:00:00Z',
  ...over,
});

const ROWS: Product[] = [
  product({}),
  product({ id: 'p2', name: 'Cloud hosting', sku: 'SVC-HOST', kind: 'service', kindLabel: 'Service', defaultPrice: 1200.5, currency: 'USD', tax: null }),
  product({ id: 'p3', name: 'Sorento CRM', sku: null, kind: 'software', kindLabel: 'Software', defaultPrice: null, currency: null, isActive: false }),
];

const KINDS: ProductKind[] = [
  { key: 'goods', label: 'Goods' },
  { key: 'service', label: 'Service' },
  { key: 'software', label: 'Software' },
];

vi.mock('@/services/productService', () => ({
  productService: {
    listProducts: vi.fn(async () => ({ data: ROWS, total: ROWS.length, page: 0 })),
    listKinds: vi.fn(async () => KINDS),
    exportCsv: vi.fn(async () => ''),
    getDelivery: vi.fn(async () => ({
      productId: 'p3',
      productDomainBase: 'https://crm.example.com',
      buildRepo: 'owner/crm',
      boardColor: '#3b82f6',
      boardName: 'CRM board',
    })),
    setDelivery: vi.fn(),
    createProduct: vi.fn(),
    updateProduct: vi.fn(),
    deleteProduct: vi.fn(),
  },
}));

/** Also masks React 19's `_r_N_` ids, in order of first appearance. */
function stable(root: Element): string {
  const seen = new Map<string, string>();
  return parityHtml(root).replace(/_r_[0-9a-z]+_/g, (id) => {
    let name = seen.get(id);
    if (!name) {
      name = `_rid${seen.size}_`;
      seen.set(id, name);
    }
    return name;
  });
}

describe('parity (switch off): Products page', () => {
  it('list with rows, toolbar and Add product', async () => {
    const { container } = render(
      <SettingsProvider>
        <ProductsPage />
      </SettingsProvider>,
    );
    await screen.findByText('Sorento CRM');
    expect(stable(container)).toMatchSnapshot();
  });
});

describe('parity (switch off): product dialog', () => {
  it('add', () => {
    render(<ProductFormDialog kinds={KINDS} onClose={vi.fn()} onSaved={vi.fn()} />);
    expect(stable(document.body)).toMatchSnapshot();
  });

  it('edit', () => {
    render(<ProductFormDialog product={ROWS[0]} kinds={KINDS} onClose={vi.fn()} onSaved={vi.fn()} />);
    expect(stable(document.body)).toMatchSnapshot();
  });

  it('edit of a software product with its delivery config', async () => {
    render(<ProductFormDialog product={ROWS[2]} kinds={KINDS} onClose={vi.fn()} onSaved={vi.fn()} />);
    await waitFor(() => expect(screen.getByLabelText('Board name')).toHaveValue('CRM board'));
    expect(stable(document.body)).toMatchSnapshot();
  });
});
