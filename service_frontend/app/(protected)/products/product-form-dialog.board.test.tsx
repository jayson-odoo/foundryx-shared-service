import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { Product, ProductKind } from '@/services/productService';
import { ProductFormDialog } from './product-form-dialog';

const getDelivery = vi.fn();
const setDelivery = vi.fn();
const updateProduct = vi.fn();
const createProduct = vi.fn();
vi.mock('@/services/productService', () => ({
  productService: {
    getDelivery: (...a: unknown[]) => getDelivery(...a),
    setDelivery: (...a: unknown[]) => setDelivery(...a),
    updateProduct: (...a: unknown[]) => updateProduct(...a),
    createProduct: (...a: unknown[]) => createProduct(...a),
  },
}));

const KINDS = [
  { key: 'software', label: 'Software' },
  { key: 'service', label: 'Service' },
] as unknown as ProductKind[];

const SOFTWARE = {
  id: 'p1',
  name: 'Sorento CRM',
  kind: 'software',
  sku: null,
  defaultPrice: null,
  tax: null,
  currency: null,
  uom: null,
  isActive: true,
} as unknown as Product;

beforeEach(() => {
  getDelivery.mockReset().mockResolvedValue({
    productId: 'p1',
    productDomainBase: 'https://fe-sorento.foundryx.my',
    buildRepo: 'jayson-odoo/old-repo',
    boardColor: null,
    boardName: null,
  });
  setDelivery.mockReset().mockResolvedValue({});
  updateProduct.mockReset().mockResolvedValue(SOFTWARE);
  createProduct.mockReset().mockResolvedValue(SOFTWARE);
});

/** Lane SS-MULTI-PRODUCT-BOARD (AC-MPB-8): a software product sets its own
 * feedback board colour + name on this dialog (no backend configuration). */
describe('ProductFormDialog feedback board look', () => {
  it('shows Board colour + Board name prefilled from the delivery config', async () => {
    getDelivery.mockResolvedValue({
      productId: 'p1', productDomainBase: null, buildRepo: null, boardColor: '#3b82f6', boardName: 'Sorento CRM',
    });
    render(<ProductFormDialog product={SOFTWARE} kinds={KINDS} onClose={vi.fn()} onSaved={vi.fn()} />);
    const color = await screen.findByLabelText('Board colour');
    await waitFor(() => expect(color).toHaveValue('#3b82f6'));
    expect(screen.getByLabelText('Board name')).toHaveValue('Sorento CRM');
  });

  it('save sends only the board fields when only they changed', async () => {
    render(<ProductFormDialog product={SOFTWARE} kinds={KINDS} onClose={vi.fn()} onSaved={vi.fn()} />);
    const color = await screen.findByLabelText('Board colour');
    await waitFor(() => expect(screen.getByLabelText('Build repository')).toHaveValue('jayson-odoo/old-repo'));
    fireEvent.change(color, { target: { value: '#3B82F6' } });
    fireEvent.change(screen.getByLabelText('Board name'), { target: { value: 'Sorento CRM' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    await waitFor(() => expect(setDelivery).toHaveBeenCalledTimes(1));
    expect(setDelivery).toHaveBeenCalledWith('p1', { boardColor: '#3b82f6', boardName: 'Sorento CRM' });
  });

  it('clearing the colour sends null (back to the default look)', async () => {
    getDelivery.mockResolvedValue({
      productId: 'p1', productDomainBase: null, buildRepo: null, boardColor: '#3b82f6', boardName: null,
    });
    render(<ProductFormDialog product={SOFTWARE} kinds={KINDS} onClose={vi.fn()} onSaved={vi.fn()} />);
    const color = await screen.findByLabelText('Board colour');
    await waitFor(() => expect(color).toHaveValue('#3b82f6'));
    fireEvent.change(color, { target: { value: '' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    await waitFor(() => expect(setDelivery).toHaveBeenCalledTimes(1));
    expect(setDelivery).toHaveBeenCalledWith('p1', { boardColor: null });
  });

  it('a colour that is not #rrggbb shows an error next to the field and saves nothing', async () => {
    const onClose = vi.fn();
    render(<ProductFormDialog product={SOFTWARE} kinds={KINDS} onClose={onClose} onSaved={vi.fn()} />);
    const color = await screen.findByLabelText('Board colour');
    await waitFor(() => expect(screen.getByLabelText('Build repository')).toHaveValue('jayson-odoo/old-repo'));
    fireEvent.change(color, { target: { value: 'blue' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    expect(await screen.findByText('Enter the colour as #rrggbb.')).toBeInTheDocument();
    expect(setDelivery).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
  });
});
