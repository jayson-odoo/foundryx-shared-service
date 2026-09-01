import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { AutocountEntityConfig } from '@/types/autocount';
import { EntitySourceDialog } from './entity-source-dialog';

function entity(over: Partial<AutocountEntityConfig> = {}): AutocountEntityConfig {
  return {
    id: 'e1',
    entityType: 'customer',
    syncMode: 'SCHEDULED_REVIEW',
    sourceImpl: 'autocount_read',
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

describe('EntitySourceDialog (plan 22 S2, AC-22-08 - a guarded switch)', () => {
  it('opens on the current source with the switch withheld until it changes', () => {
    render(<EntitySourceDialog entity={entity()} onClose={vi.fn()} onSave={vi.fn()} />);
    expect(screen.getByRole('combobox', { name: 'Entity source' })).toHaveTextContent('AutoCount API');
    expect(screen.getByTestId('save-source')).toBeDisabled();
    expect(screen.queryByTestId('source-switch-warning')).not.toBeInTheDocument();
  });

  it('states the consequence and confirms with the target source named', async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(<EntitySourceDialog entity={entity()} onClose={vi.fn()} onSave={onSave} />);
    fireEvent.click(screen.getByRole('combobox', { name: 'Entity source' }));
    fireEvent.click(await screen.findByRole('option', { name: 'Database' }));
    expect(screen.getByTestId('source-switch-warning')).toHaveTextContent(/database task/i);
    const confirm = screen.getByTestId('save-source');
    expect(confirm).toBeEnabled();
    expect(confirm).toHaveTextContent('Switch to Database');
    fireEvent.click(confirm);
    expect(onSave).toHaveBeenCalledWith('customer', 'sql_db');
  });

  it('warns that an active task is paused when switching back to the API', async () => {
    render(
      <EntitySourceDialog entity={entity({ sourceImpl: 'sql_db' })} onClose={vi.fn()} onSave={vi.fn()} />,
    );
    fireEvent.click(screen.getByRole('combobox', { name: 'Entity source' }));
    fireEvent.click(await screen.findByRole('option', { name: 'AutoCount API' }));
    expect(screen.getByTestId('source-switch-warning')).toHaveTextContent(/paused/i);
  });

  // ── plan 22 S4 - a DB-only entity never offers the API path (AC-22-23) ────

  it('offers ONLY Database for a masters-fan-out entity with no vendor payload', async () => {
    render(
      <EntitySourceDialog
        entity={entity({ entityType: 'product', sourceImpl: 'sql_db' })}
        onClose={vi.fn()}
        onSave={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole('combobox', { name: 'Entity source' }));
    expect(await screen.findByRole('option', { name: 'Database' })).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: 'AutoCount API' })).not.toBeInTheDocument();
  });

  it('shows the CURRENT value for a legacy autocount_read entity outside the capable set (S1)', () => {
    // A `product` row that predates masters-fan-out (this build has no
    // AutoCount API route for it, `AC_API_CAPABLE_ENTITY_TYPES`) but still
    // carries `sourceImpl: 'autocount_read'` from before that changed - the
    // picker must show its REAL current value, never a blank placeholder.
    render(
      <EntitySourceDialog
        entity={entity({ entityType: 'product', sourceImpl: 'autocount_read' })}
        onClose={vi.fn()}
        onSave={vi.fn()}
      />,
    );
    const combobox = screen.getByRole('combobox', { name: 'Entity source' });
    expect(combobox).toHaveTextContent('AutoCount API');
    expect(combobox).not.toHaveTextContent('Select');
  });

  it('still offers both sources for the existing API-capable entities', async () => {
    render(
      <EntitySourceDialog
        entity={entity({ entityType: 'goods_received_note', sourceImpl: 'autocount_read' })}
        onClose={vi.fn()}
        onSave={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole('combobox', { name: 'Entity source' }));
    expect(await screen.findByRole('option', { name: 'Database' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'AutoCount API' })).toBeInTheDocument();
  });
});
