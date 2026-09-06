/**
 * "Manage segments" dialog (D-A2-3, AC-CTM-06/47, amended 2026-09-06 review
 * round 1). The filter-edit popover reuses the SAME `FilterBuilder` the
 * list's Filters button opens, seeded via `initialValue` (plan §"one
 * filter-tree editor in the system"). Applying without changing anything
 * must round-trip the EXACT saved tree back out - a silent reshape here
 * would corrupt a segment nobody touched. Also covers rename + delete
 * (permission-gated by the caller, `segments.manage`, see `page.tsx`).
 *
 * Delete no longer opens an `AlertDialog` (a design-language hard-fail) - it
 * parks on the CORE grace-window engine (`contact_segments.delete`) via
 * `useDeferredAction`, same as every other destructive action in this
 * module.
 */
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import type { FilterGroup } from '@/types/resource';
import type { ContactSegment } from '@/types/omnichannel';
import { ManageSegmentsDialog } from './manage-segments-dialog';

const park = vi.fn();
const cancelPark = vi.fn();
const current = vi.fn();
vi.mock('@/services/pending-actions-service', () => ({
  pendingActionsService: {
    park: (...a: unknown[]) => park(...a),
    cancel: (...a: unknown[]) => cancelPark(...a),
    current: (...a: unknown[]) => current(...a),
  },
}));

const toastCustom = vi.fn(() => 'toast-id-1');
const toastDismiss = vi.fn();
const toastSuccess = vi.fn();
const toastError = vi.fn();
vi.mock('sonner', () => ({
  toast: {
    custom: (...a: unknown[]) => toastCustom(...a),
    dismiss: (...a: unknown[]) => toastDismiss(...a),
    success: (...a: unknown[]) => toastSuccess(...a),
    error: (...a: unknown[]) => toastError(...a),
  },
}));

const FILTER: FilterGroup = {
  kind: 'group',
  combinator: 'and',
  rules: [{ kind: 'condition', field: 'priority', operator: 'in', value: ['HIGH', 'URGENT'] }],
};

const SEGMENT: ContactSegment = {
  id: 'seg-1',
  workspaceId: 'wsp-1',
  name: 'Urgent & high priority',
  description: 'Contacts flagged HIGH or URGENT.',
  filter: FILTER,
  createdAt: '2026-01-01T00:00:00Z',
  updatedAt: '2026-01-01T00:00:00Z',
};

const FIELDS = [
  {
    field: 'priority',
    label: 'Priority',
    type: 'enum' as const,
    options: [
      { label: 'Low', value: 'LOW' },
      { label: 'Medium', value: 'MEDIUM' },
      { label: 'High', value: 'HIGH' },
      { label: 'Urgent', value: 'URGENT' },
    ],
  },
];

beforeEach(() => {
  vi.clearAllMocks();
  current.mockResolvedValue({ pending: null, lastOutcome: null });
});

describe('ManageSegmentsDialog', () => {
  it('round-trips the saved FilterGroup unchanged when Apply is clicked with no edits', async () => {
    const user = userEvent.setup();
    const onEditFilter = vi.fn().mockResolvedValue(undefined);
    render(
      <ManageSegmentsDialog
        open
        onOpenChange={vi.fn()}
        segments={[SEGMENT]}
        filterFields={FIELDS}
        onRename={vi.fn()}
        onEditFilter={onEditFilter}
      />,
    );

    await user.click(screen.getByRole('button', { name: `Edit ${SEGMENT.name} filter` }));
    await user.click(await screen.findByRole('button', { name: 'Apply' }));

    await waitFor(() => expect(onEditFilter).toHaveBeenCalledWith(SEGMENT.id, FILTER));
  });

  it('renames a segment on blur/Enter', async () => {
    const user = userEvent.setup();
    const onRename = vi.fn().mockResolvedValue(undefined);
    render(
      <ManageSegmentsDialog
        open
        onOpenChange={vi.fn()}
        segments={[SEGMENT]}
        filterFields={FIELDS}
        onRename={onRename}
        onEditFilter={vi.fn()}
      />,
    );

    await user.click(screen.getByRole('button', { name: `Rename ${SEGMENT.name}` }));
    const input = screen.getByDisplayValue(SEGMENT.name);
    await user.clear(input);
    await user.type(input, 'VIP contacts{Enter}');

    await waitFor(() => expect(onRename).toHaveBeenCalledWith(SEGMENT.id, 'VIP contacts'));
  });

  it('deletes via the grace-window engine - NO confirm dialog', async () => {
    const user = userEvent.setup();
    const onDeleted = vi.fn();
    park.mockResolvedValue({
      id: 'pa1',
      commitAt: new Date(Date.now() + 10_000).toISOString(),
      windowSeconds: 10,
    });
    render(
      <ManageSegmentsDialog
        open
        onOpenChange={vi.fn()}
        segments={[SEGMENT]}
        filterFields={FIELDS}
        onRename={vi.fn()}
        onEditFilter={vi.fn()}
        onDeleted={onDeleted}
      />,
    );

    await user.click(screen.getByRole('button', { name: `Delete ${SEGMENT.name}` }));

    // No AlertDialog anywhere - the grace window IS the confirmation.
    expect(screen.queryByText(/cannot be undone/i)).not.toBeInTheDocument();
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();

    await waitFor(() =>
      expect(park).toHaveBeenCalledWith('contact_segments.delete', 'contact_segment', SEGMENT.id, undefined),
    );
    // The countdown toast rendered (mirrors every other row-surface deferred
    // delete in this module).
    expect(toastCustom).toHaveBeenCalled();
  });
});
