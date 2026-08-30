import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { AutocountEntityConfig } from '@/types/autocount';
import { AddEntityControl } from './add-entity-control';

function entity(over: Partial<AutocountEntityConfig> = {}): AutocountEntityConfig {
  return {
    id: 'e1',
    entityType: 'product_category',
    syncMode: 'SCHEDULED_REVIEW',
    sourceImpl: 'sql_db',
    recordCap: 200,
    initialLookbackDays: 30,
    enabled: true,
    lastSuccessAt: null,
    lastAttemptAt: null,
    watermarkAt: null,
    consecutiveFailures: 0,
    lastError: null,
    etlStatus: 'draft',
    ...over,
  };
}

describe('AddEntityControl (plan 22 S4, AC-22-23)', () => {
  it('offers only the masters fan-out entities NOT already configured', async () => {
    render(<AddEntityControl entities={[entity({ entityType: 'product_category' })]} onAdd={vi.fn()} />);
    fireEvent.click(screen.getByRole('combobox', { name: 'Add entity' }));
    expect(await screen.findByRole('option', { name: 'Unit of measure' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'Warehouse' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'Product' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'Sales agent' })).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: 'Product category' })).not.toBeInTheDocument();
  });

  it('withholds Configure until an entity is picked, then calls onAdd with it', async () => {
    const onAdd = vi.fn();
    render(<AddEntityControl entities={[]} onAdd={onAdd} />);
    expect(screen.getByTestId('add-entity-configure')).toBeDisabled();
    fireEvent.click(screen.getByRole('combobox', { name: 'Add entity' }));
    fireEvent.click(await screen.findByRole('option', { name: 'Product' }));
    const button = screen.getByTestId('add-entity-configure');
    expect(button).toBeEnabled();
    fireEvent.click(button);
    expect(onAdd).toHaveBeenCalledWith('product');
  });

  it('renders nothing once every masters entity is already configured', () => {
    const all: AutocountEntityConfig[] = [
      'product_category', 'unit_of_measure', 'warehouse', 'product', 'sales_agent',
    ].map((entityType) => entity({ id: entityType, entityType }));
    const { container } = render(<AddEntityControl entities={all} onAdd={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });
});
