/**
 * Products with the Foundryx UIUX switch on (slice W1-PRODUCTS): the red
 * action follows typing, RM for MYR and ISO codes otherwise, the Tax %
 * stepper's limits, Hold to Copy on SKU and price, the edit toast's Undo,
 * and Delete keeping its deferred window with "Undo". Switch off is pinned by
 * `__parity__/products.parity.test.tsx`.
 */
import type { ReactNode } from 'react';
import { act, fireEvent, render, renderHook, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { FX_DEFAULT_THEME } from '@/lib/fx/cookies';
import { FxProvider } from '@/providers/fx-provider';
import { SettingsProvider } from '@/providers/settings-provider';
import { resetPageActionsForTests } from '@/components/fx/actions/page-actions-context';
import { FxDeferredCountdown } from '@/components/fx/toast/fx-deferred-countdown';
import { presentContinuous } from '@/lib/deferred-verb';
import type { Product, ProductKind } from '@/services/productService';
import ProductsPage from './page';
import { ProductFormDialog } from './product-form-dialog';
import { fxCurrencyCodes, fxProductActionLabel, fxTaxStep, productRestorePayload } from './product-fx';
import { deliveryRestoreBody } from './use-product-form';
import { useFxProductSavedToast } from './use-fx-product-saved-toast';
import { useProductsListConfig } from './use-products-list-config';

const svc = vi.hoisted(() => ({
  listProducts: vi.fn(),
  listKinds: vi.fn(),
  exportCsv: vi.fn(),
  getDelivery: vi.fn(),
  setDelivery: vi.fn(),
  createProduct: vi.fn(),
  updateProduct: vi.fn(),
  deleteProduct: vi.fn(),
}));
vi.mock('@/services/productService', () => ({ productService: svc }));

const fxDone = vi.hoisted(() => vi.fn());
vi.mock('@/lib/toast', async (orig) => {
  const real = (await orig()) as { toast: Record<string, unknown> };
  return { toast: { ...real.toast, fxDone, error: vi.fn(), success: vi.fn() } };
});

vi.mock('next-themes', () => ({ useTheme: () => ({ theme: 'light', setTheme: vi.fn() }) }));
vi.mock('next/navigation', () => ({
  useRouter: vi.fn(() => ({ push: vi.fn(), prefetch: vi.fn(), replace: vi.fn(), back: vi.fn() })),
  useSearchParams: vi.fn(() => new URLSearchParams()),
  usePathname: vi.fn(() => '/products'),
}));
vi.mock('next-auth/react', () => ({
  useSession: () => ({
    data: {
      user: {
        name: 'Nurul Huda',
        timezone: 'Asia/Kuala_Lumpur',
        permissions: ['products.read', 'products.create', 'products.update', 'products.delete'],
      },
    },
    status: 'authenticated',
  }),
}));
vi.mock('@/lib/impersonation-store', () => ({ useImpersonationSession: () => null }));
vi.mock('@/services/terminology-service', () => ({
  terminologyService: { getTerminology: vi.fn().mockResolvedValue({}) },
}));
vi.mock('@/providers/import-activity-provider', () => ({
  useImportActivity: () => ({ openImport: vi.fn() }),
}));
vi.mock('@/services/preferences-service', () => ({
  preferencesService: { get: vi.fn().mockResolvedValue(null), save: vi.fn().mockResolvedValue(undefined) },
}));

const product = (over: Partial<Product> = {}): Product => ({
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
const KINDS: ProductKind[] = [
  { key: 'goods', label: 'Goods' },
  { key: 'service', label: 'Service' },
];

function On({ children }: { children: ReactNode }) {
  return (
    <FxProvider initial initialTheme={FX_DEFAULT_THEME}>
      <SettingsProvider>{children}</SettingsProvider>
    </FxProvider>
  );
}

beforeEach(() => {
  Object.values(svc).forEach((fn) => fn.mockReset());
  fxDone.mockReset();
  svc.listKinds.mockResolvedValue(KINDS);
  svc.updateProduct.mockImplementation(async (id: string, body: Partial<Product>) => product({ id, ...body }));
  svc.createProduct.mockImplementation(async (body: Partial<Product>) => product({ id: 'new', ...body }));
});
afterEach(() => resetPageActionsForTests());

describe('words and values', () => {
  it('the red action names the product and its price', () => {
    expect(fxProductActionLabel({ isEdit: false, name: ' ', price: 189, currency: 'MYR' })).toBe('Add product');
    expect(fxProductActionLabel({ isEdit: true, name: '', price: null, currency: null })).toBe('Save changes');
    expect(fxProductActionLabel({ isEdit: false, name: 'Barcode scanner', price: 189, currency: 'MYR' })).toBe(
      'Add Barcode scanner at RM 189.00',
    );
    expect(fxProductActionLabel({ isEdit: true, name: 'Cloud hosting', price: 1200.5, currency: 'USD' })).toBe(
      'Save Cloud hosting at USD 1,200.50',
    );
    expect(fxProductActionLabel({ isEdit: false, name: 'Setup', price: null, currency: 'MYR' })).toBe('Add Setup');
  });

  it('keeps a product currency that is not on the common list', () => {
    expect(fxCurrencyCodes('bnd')[0]).toBe('BND');
    expect(fxCurrencyCodes('MYR').filter((c) => c === 'MYR')).toHaveLength(1);
    expect(fxCurrencyCodes(null)).toContain('USD');
  });

  it('tax steps by whole points unless the rate holds decimals', () => {
    expect(fxTaxStep(8)).toBe(1);
    expect(fxTaxStep(8.25)).toBe(0.01);
  });

  it('Undo writes back every field as it was', () => {
    expect(productRestorePayload(product({ sku: null, tax: null }))).toEqual({
      name: 'Barcode scanner',
      kind: 'goods',
      sku: null,
      defaultPrice: 189,
      tax: null,
      currency: 'MYR',
      uom: 'unit',
      isActive: true,
    });
  });

  it('a delivery change puts back only what was sent, and never a new domain base', () => {
    const initial = { domainBase: '', buildRepo: 'o/r', boardColor: '#112233', boardName: '' };
    expect(deliveryRestoreBody({ boardColor: '#000000', boardName: 'B' }, initial)).toEqual({
      boardColor: '#112233',
      boardName: null,
    });
    expect(deliveryRestoreBody({ buildRepo: null }, initial)).toEqual({ buildRepo: 'o/r' });
    expect(deliveryRestoreBody({ productDomainBase: 'https://x.example', buildRepo: 'o/r' }, initial)).toBeNull();
    expect(
      deliveryRestoreBody({ productDomainBase: 'https://y.example', buildRepo: null }, { ...initial, domainBase: 'https://x.example' }),
    ).toEqual({ productDomainBase: 'https://x.example', buildRepo: 'o/r' });
  });
});

describe('product dialog, switch on', () => {
  it('the red action follows typing and is greyed with no name', () => {
    render(<ProductFormDialog kinds={KINDS} onClose={vi.fn()} onSaved={vi.fn()} />, { wrapper: On });
    const main = screen.getByRole('button', { name: 'Add product' });
    expect(main).toHaveAttribute('aria-disabled', 'true');
    expect(screen.getByText('Enter a name.')).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Barcode scanner' } });
    const price = screen.getByLabelText('Default price');
    fireEvent.change(price, { target: { value: '189' } });
    fireEvent.blur(price);
    expect(price).toHaveValue('189.00');
    const named = screen.getByRole('button', { name: 'Add Barcode scanner at RM 189.00' });
    expect(named).not.toHaveAttribute('aria-disabled');
    expect(screen.queryByText('Enter a name.')).not.toBeInTheDocument();
  });

  it('shows RM for MYR and the ISO code for any other currency', () => {
    const { unmount } = render(
      <ProductFormDialog product={product()} kinds={KINDS} onClose={vi.fn()} onSaved={vi.fn()} />,
      { wrapper: On },
    );
    const box = screen.getByLabelText('Default price').parentElement as HTMLElement;
    expect(within(box).getByText('RM')).toBeInTheDocument();
    expect(screen.getByLabelText('Default price')).toHaveValue('189.00');
    unmount();
    resetPageActionsForTests();

    render(
      <ProductFormDialog
        product={product({ defaultPrice: 1200.5, currency: 'USD' })}
        kinds={KINDS}
        onClose={vi.fn()}
        onSaved={vi.fn()}
      />,
      { wrapper: On },
    );
    const usd = screen.getByLabelText('Default price').parentElement as HTMLElement;
    expect(within(usd).getByText('USD')).toBeInTheDocument();
    expect(screen.getByLabelText('Default price')).toHaveValue('1,200.50');
    expect(screen.getByRole('button', { name: 'Save Barcode scanner at USD 1,200.50' })).toBeInTheDocument();
  });

  it('Tax % stays between 0 and 100 and greys - at 0', () => {
    render(<ProductFormDialog product={product({ tax: 0 })} kinds={KINDS} onClose={vi.fn()} onSaved={vi.fn()} />, {
      wrapper: On,
    });
    const tax = screen.getByLabelText('Tax %');
    expect(screen.getByRole('button', { name: 'Decrease' })).toBeDisabled();
    fireEvent.change(tax, { target: { value: '150' } });
    fireEvent.blur(tax);
    expect(tax).toHaveValue('100');
    expect(screen.getByRole('button', { name: 'Increase' })).toBeDisabled();
    fireEvent.change(tax, { target: { value: '-4' } });
    fireEvent.blur(tax);
    expect(tax).toHaveValue('0');
  });

  it('a rate with decimals is kept when the field is only visited', async () => {
    const onSaved = vi.fn();
    render(<ProductFormDialog product={product({ tax: 8.25 })} kinds={KINDS} onClose={vi.fn()} onSaved={onSaved} />, {
      wrapper: On,
    });
    const tax = screen.getByLabelText('Tax %');
    fireEvent.focus(tax);
    fireEvent.blur(tax);
    expect(tax).toHaveValue('8.25');
    fireEvent.click(screen.getByRole('button', { name: /^Save Barcode scanner/ }));
    await waitFor(() => expect(svc.updateProduct).toHaveBeenCalled());
    expect(svc.updateProduct.mock.calls[0][1]).toMatchObject({ tax: 8.25 });
  });

  it('saves the same payload as with the switch off and reports what it was before', async () => {
    const onSaved = vi.fn();
    const onClose = vi.fn();
    render(<ProductFormDialog product={product()} kinds={KINDS} onClose={onClose} onSaved={onSaved} />, {
      wrapper: On,
    });
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Barcode scanner Pro' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save Barcode scanner Pro at RM 189.00' }));
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    expect(svc.updateProduct).toHaveBeenCalledWith('p1', {
      name: 'Barcode scanner Pro',
      kind: 'goods',
      sku: 'HW-SCAN-01',
      defaultPrice: 189,
      tax: 8,
      currency: 'MYR',
      uom: 'unit',
      isActive: true,
    });
    expect(onSaved.mock.calls[0][0].before).toEqual(product());
    expect(onClose).toHaveBeenCalled();
  });
});

describe('edit toast, switch on', () => {
  it('names the product, who and when, and Undo writes it back', async () => {
    const reload = vi.fn();
    const { result } = renderHook(() => useFxProductSavedToast(reload), { wrapper: On });
    const before = product();
    act(() => result.current!({ saved: product({ name: 'Barcode scanner Pro' }), before }));
    const input = fxDone.mock.calls[0][0];
    expect(input.what).toBe('Barcode scanner Pro saved');
    expect(input.byWhom).toMatch(/^Nurul Huda at \d{1,2}:\d{2} (am|pm)$/);
    expect(typeof input.undo).toBe('function');
    input.undo();
    await waitFor(() => expect(svc.updateProduct).toHaveBeenCalledWith('p1', productRestorePayload(before)));
    await waitFor(() => expect(reload).toHaveBeenCalled());
  });

  it('an added product, or a change the API cannot put back, has no Undo', () => {
    const { result } = renderHook(() => useFxProductSavedToast(vi.fn()), { wrapper: On });
    act(() => result.current!({ saved: product() }));
    expect(fxDone.mock.calls[0][0]).toMatchObject({ what: 'Barcode scanner added', undo: undefined });
    act(() => result.current!({ saved: product(), before: product(), deliveryBefore: null }));
    expect(fxDone.mock.calls[1][0].undo).toBeUndefined();
  });

  it('is off with the switch off', () => {
    const { result } = renderHook(() => useFxProductSavedToast(vi.fn()));
    expect(result.current).toBeNull();
  });
});

describe('list, switch on', () => {
  const handlers = () => ({ onCreate: vi.fn(), onEdit: vi.fn(), onDelete: vi.fn() });

  it('prices read RM for MYR and the ISO code otherwise; SKU and price Hold to Copy', () => {
    const { result } = renderHook(() => useProductsListConfig(handlers()), { wrapper: On });
    expect(result.current.fx).toMatchObject({ mainActionId: 'create', copyable: ['sku', 'price'], noun: 'products' });
    const price = result.current.columns.find((c) => c.id === 'price')!;
    const cell = price.cell as (ctx: { row: { original: Product } }) => ReactNode;
    const { container, rerender } = render(<>{cell({ row: { original: product() } })}</>);
    expect(container).toHaveTextContent('RM 189.00');
    rerender(<>{cell({ row: { original: product({ defaultPrice: 1200.5, currency: 'USD' }) } })}</>);
    expect(container).toHaveTextContent('USD 1,200.50');
  });

  it('Delete stays the deferred action (no confirm, no run)', () => {
    const { result } = renderHook(() => useProductsListConfig(handlers()), { wrapper: On });
    const del = result.current.actions.find((a) => a.id === 'delete')!;
    expect(del.deferred).toEqual({ actionKey: 'products.delete', entityType: 'product' });
    expect(del.confirm).toBeUndefined();
    expect(del.run).toBeUndefined();
  });

  it('the page: Add product is the red action, SKU and price cells Hold to Copy', async () => {
    svc.listProducts.mockResolvedValue({
      data: [product(), product({ id: 'p2', name: 'Cloud hosting', sku: 'SVC-HOST', defaultPrice: 1200.5, currency: 'USD' })],
      total: 2,
      page: 0,
    });
    const { container } = render(<ProductsPage />, { wrapper: On });
    const scroller = () => container.querySelector('[data-slot="data-grid-scroller"]') as HTMLElement;
    await waitFor(() => expect(within(scroller()).getByText('Cloud hosting')).toBeInTheDocument());
    expect(container.querySelector('[data-fx-header-actions]')).toContainElement(
      screen.getByRole('button', { name: 'Add product' }),
    );
    const sku = within(scroller()).getByText('SVC-HOST');
    expect(sku.closest('[data-fx-h2c]')).not.toBeNull();
    const price = within(scroller()).getByText('USD 1,200.50');
    expect(price.closest('[data-fx-h2c]')).not.toBeNull();
    expect(within(scroller()).getByText('Cloud hosting').closest('[data-fx-h2c]')).toBeNull();
  });

  it('the empty list names products', async () => {
    svc.listProducts.mockResolvedValue({ data: [], total: 0, page: 0 });
    render(<ProductsPage />, { wrapper: On });
    expect(await screen.findByText('Products you add show here.')).toBeInTheDocument();
  });

  it('a deleted product counts down its 10 s window with Undo', () => {
    const onCancel = vi.fn();
    render(
      <FxDeferredCountdown
        verb={presentContinuous('Delete')}
        commitAt={new Date(Date.now() + 10_000).toISOString()}
        windowSeconds={10}
        onCancel={onCancel}
        fxSurface="toast"
      />,
      { wrapper: On },
    );
    expect(screen.getByRole('timer')).toHaveTextContent('Deleting in 10 s');
    fireEvent.click(screen.getByRole('button', { name: 'Undo' }));
    expect(onCancel).toHaveBeenCalled();
  });
});
