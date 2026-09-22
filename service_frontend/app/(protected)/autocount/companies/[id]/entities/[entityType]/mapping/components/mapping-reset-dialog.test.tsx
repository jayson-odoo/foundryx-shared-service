import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/lib/api-client';
import type { AutocountMappingResetPreview, AutocountMappingView } from '@/types/autocount';
import { MappingResetDialog } from './mapping-reset-dialog';

/**
 * `MappingResetDialog` (sprint-5/12, Group B - AC-12-20/22/23). Mocked at
 * the SERVICE boundary (not the hook) so `useMappingReset`'s own wiring is
 * exercised for real - the same convention `use-mapping-reset.test.ts` uses
 * for the hook in isolation; together they cover every AC-12-20 state the
 * mock is required to tune before the backend exists.
 */

const resetMappingToPreset = vi.fn();
vi.mock('@/services/autocount-service', () => ({
  autocountService: {
    resetMappingToPreset: (...a: unknown[]) => resetMappingToPreset(...a),
  },
}));

const toastSuccess = vi.fn();
vi.mock('@/lib/toast', () => ({
  toast: { success: (...a: unknown[]) => toastSuccess(...a) },
}));

const PREVIEW_MIXED: AutocountMappingResetPreview = {
  label: 'Item (open REST API)',
  rows: [
    { canonicalField: 'code', sourcePath: 'ItemCode', transform: 'string', formula: null, enabled: true, isRequired: true, change: 'unchanged' },
    { canonicalField: 'name', sourcePath: 'ItemCode', transform: 'string', formula: null, enabled: true, isRequired: false, change: 'changed' },
    {
      canonicalField: 'description',
      sourcePath: 'Description',
      transform: 'string',
      formula: 'trim(if(default(Desc2, "") != "", concat(Description, " ", Desc2), Description))',
      enabled: true,
      isRequired: false,
      change: 'added',
    },
    {
      canonicalField: 'uom_code',
      sourcePath: 'BaseUOM',
      transform: 'string',
      formula: null,
      enabled: false,
      isRequired: false,
      change: 'changed',
      disabledReason: 'withheld by the preset',
    },
    {
      canonicalField: 'list_price',
      sourcePath: 'BaseUOMPrice',
      transform: 'string',
      formula: 'if(number(value) <= 0, 0, number(value))',
      enabled: false,
      isRequired: false,
      change: 'added',
      disabledReason: 'column not returned by the source',
    },
  ],
  removed: [{ canonicalField: 'legacy_field', sourcePath: 'OldColumn', transform: 'string', formula: null }],
};

const PREVIEW_EMPTY: AutocountMappingResetPreview = {
  label: 'Item (open REST API)',
  rows: [
    { canonicalField: 'code', sourcePath: 'ItemCode', transform: 'string', formula: null, enabled: true, isRequired: true, change: 'unchanged' },
  ],
  removed: [],
};

const VIEW: AutocountMappingView = {
  entityType: 'product',
  rows: [],
  sorentoFields: [],
  acFields: [],
  lineSorentoFields: [],
  lineAcFields: [],
  hasPreset: true,
};

function renderDialog(onApplied = vi.fn()) {
  return render(
    <MappingResetDialog
      open
      onOpenChange={vi.fn()}
      companyId="company-1"
      entityType="product"
      onApplied={onApplied}
    />,
  );
}

describe('MappingResetDialog (AC-12-20/22/23)', () => {
  it('shows a loading state, never a bare "Loading..." string', () => {
    resetMappingToPreset.mockReturnValue(new Promise(() => {}));
    renderDialog();
    expect(screen.getByTestId('mapping-reset-loading')).toBeInTheDocument();
    expect(screen.queryByText('Loading...')).not.toBeInTheDocument();
  });

  it('renders one row per change kind, the disabled reason, and the Removed section', async () => {
    resetMappingToPreset.mockResolvedValue(PREVIEW_MIXED);
    renderDialog();
    await waitFor(() => expect(screen.getByTestId('mapping-reset-rows')).toBeInTheDocument());

    expect(screen.getByText('Unchanged')).toBeInTheDocument();
    // Two rows carry `change: 'changed'` (name, uom_code).
    expect(screen.getAllByText('Changed').length).toBe(2);
    // Two rows carry `change: 'added'` (description, list_price).
    expect(screen.getAllByText('Added').length).toBe(2);
    // Each disabled row names its OWN cause (UAC amendment 2026-09-22) - a
    // single shared string would misreport `uom_code`, whose column IS
    // returned by the source.
    expect(screen.getByText(/Disabled - withheld by the preset/)).toBeInTheDocument();
    expect(screen.getByText(/Disabled - column not returned by the source/)).toBeInTheDocument();
    expect(screen.getByTestId('mapping-reset-removed')).toBeInTheDocument();
    // The section heading AND the removed row's own badge both read "Removed".
    expect(screen.getAllByText('Removed').length).toBe(2);
    expect(screen.getByText('OldColumn')).toBeInTheDocument();

    // Reset mapping is enabled once a real (non-empty) diff has loaded.
    expect(screen.getByRole('button', { name: /reset mapping/i })).toBeEnabled();
  });

  it('an empty diff shows "already matches" and disables the primary button', async () => {
    resetMappingToPreset.mockResolvedValue(PREVIEW_EMPTY);
    renderDialog();
    await waitFor(() => expect(screen.getByTestId('mapping-reset-empty')).toBeInTheDocument());
    expect(screen.getByText('This mapping already matches the preset.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /reset mapping/i })).toBeDisabled();
  });

  it('the "no preset" 422 surfaces inline, the primary button stays disabled', async () => {
    resetMappingToPreset.mockRejectedValue(new ApiError('No preset is registered for this entity.', 422));
    renderDialog();
    await waitFor(() => expect(screen.getByTestId('mapping-reset-load-error')).toBeInTheDocument());
    expect(screen.getByText('No preset is registered for this entity.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /reset mapping/i })).toBeDisabled();
  });

  it('apply success: toasts, calls onApplied with the fresh view, and closes', async () => {
    resetMappingToPreset.mockResolvedValueOnce(PREVIEW_MIXED).mockResolvedValueOnce(VIEW);
    const onOpenChange = vi.fn();
    const onApplied = vi.fn();
    render(
      <MappingResetDialog
        open
        onOpenChange={onOpenChange}
        companyId="company-1"
        entityType="product"
        onApplied={onApplied}
      />,
    );
    await waitFor(() => expect(screen.getByRole('button', { name: /reset mapping/i })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: /reset mapping/i }));

    await waitFor(() => expect(onApplied).toHaveBeenCalledWith(VIEW));
    expect(toastSuccess).toHaveBeenCalledWith('Mapping reset to preset.');
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it('apply failure keeps the dialog open with the server message, never calling onApplied', async () => {
    resetMappingToPreset
      .mockResolvedValueOnce(PREVIEW_MIXED)
      .mockRejectedValueOnce(new ApiError('That reset could not be applied.', 500));
    const onOpenChange = vi.fn();
    const onApplied = vi.fn();
    render(
      <MappingResetDialog
        open
        onOpenChange={onOpenChange}
        companyId="company-1"
        entityType="product"
        onApplied={onApplied}
      />,
    );
    await waitFor(() => expect(screen.getByRole('button', { name: /reset mapping/i })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: /reset mapping/i }));

    await waitFor(() => expect(screen.getByTestId('mapping-reset-apply-error')).toBeInTheDocument());
    expect(screen.getByText('That reset could not be applied.')).toBeInTheDocument();
    expect(onApplied).not.toHaveBeenCalled();
    expect(onOpenChange).not.toHaveBeenCalledWith(false);
    // The already-loaded diff stays visible.
    expect(screen.getByTestId('mapping-reset-rows')).toBeInTheDocument();
  });
});
