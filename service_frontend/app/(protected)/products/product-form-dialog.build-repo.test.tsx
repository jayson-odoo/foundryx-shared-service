import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/lib/api-client';
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
  });
  setDelivery.mockReset().mockResolvedValue({});
  updateProduct.mockReset().mockResolvedValue(SOFTWARE);
  createProduct.mockReset().mockResolvedValue(SOFTWARE);
});

describe('ProductFormDialog build repository (AC-STB-02)', () => {
  it('AC-STB-02 a software product shows a "Build repository" field prefilled from the delivery config', async () => {
    render(<ProductFormDialog product={SOFTWARE} kinds={KINDS} onClose={vi.fn()} onSaved={vi.fn()} />);
    const input = await screen.findByLabelText('Build repository');
    await waitFor(() => expect(input).toHaveValue('jayson-odoo/old-repo'));
    expect(screen.getByLabelText('Product domain base')).toBeInTheDocument();
  });

  it('AC-STB-02 a non-software product has no Build repository field', () => {
    const service = { ...SOFTWARE, kind: 'service' } as Product;
    render(<ProductFormDialog product={service} kinds={KINDS} onClose={vi.fn()} onSaved={vi.fn()} />);
    expect(screen.queryByLabelText('Build repository')).not.toBeInTheDocument();
  });

  it('AC-STB-02 save writes both fields through setDelivery', async () => {
    const onSaved = vi.fn();
    render(<ProductFormDialog product={SOFTWARE} kinds={KINDS} onClose={vi.fn()} onSaved={onSaved} />);
    const input = await screen.findByLabelText('Build repository');
    await waitFor(() => expect(input).toHaveValue('jayson-odoo/old-repo'));
    fireEvent.change(input, { target: { value: 'jayson-odoo/sorento-crm' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    await waitFor(() => expect(setDelivery).toHaveBeenCalledTimes(1));
    expect(setDelivery).toHaveBeenCalledWith('p1', {
      productDomainBase: 'https://fe-sorento.foundryx.my',
      buildRepo: 'jayson-odoo/sorento-crm',
    });
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
  });

  it('AC-STB-02 a 422 on the delivery save shows inline under the field and keeps the dialog open', async () => {
    setDelivery.mockRejectedValue(
      new ApiError('Unprocessable', 422, null, {
        fieldErrors: { buildRepo: 'Use the owner/name form.' },
      }),
    );
    const onClose = vi.fn();
    render(<ProductFormDialog product={SOFTWARE} kinds={KINDS} onClose={onClose} onSaved={vi.fn()} />);
    const input = await screen.findByLabelText('Build repository');
    await waitFor(() => expect(input).toHaveValue('jayson-odoo/old-repo'));
    fireEvent.change(input, { target: { value: 'not a repo' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    expect(await screen.findByText('Use the owner/name form.')).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
  });
});
