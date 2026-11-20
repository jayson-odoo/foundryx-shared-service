/**
 * "Manage segments" dialog (D-A2-3, AC-CTM-06/47, amended 2026-09-06 review
 * rounds 1+2). The filter-edit popover reuses the SAME `FilterBuilder` the
 * list's Filters button opens, seeded via `initialValue` (plan §"one
 * filter-tree editor in the system"). Applying without changing anything
 * must round-trip the EXACT saved tree back out - a silent reshape here
 * would corrupt a segment nobody touched. Also covers rename + the delete
 * button's disabled state (permission-gated by the caller, `segments.manage`,
 * see `page.tsx`).
 *
 * Delete no longer opens an `AlertDialog` (a design-language hard-fail) and,
 * since review round 2, this dialog no longer owns the deferred-action
 * lifecycle itself - `use-segment-delete-controller.test.ts` covers the
 * actual park/cancel/commit behaviour (moved to the PAGE so a countdown
 * survives the dialog closing, should-fix 4). This file only asserts the
 * dialog's OWN contract: `onDelete` fires with the clicked row, and every
 * OTHER row's Delete button disables while `deletingId` names one segment
 * (review round 2, blocker 2 - one countdown at a time).
 */
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { FilterGroup } from '@/types/resource';
import type { ContactSegment } from '@/types/omnichannel';
import { ManageSegmentsDialog } from './manage-segments-dialog';

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

const SEGMENT_2: ContactSegment = {
  id: 'seg-2',
  workspaceId: 'wsp-1',
  name: 'VIP contacts',
  description: null,
  filter: { kind: 'group', combinator: 'and', rules: [] },
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
        deletingId={null}
        onDelete={vi.fn()}
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
        deletingId={null}
        onDelete={vi.fn()}
      />,
    );

    await user.click(screen.getByRole('button', { name: `Rename ${SEGMENT.name}` }));
    const input = screen.getByDisplayValue(SEGMENT.name);
    await user.clear(input);
    await user.type(input, 'VIP contacts{Enter}');

    await waitFor(() => expect(onRename).toHaveBeenCalledWith(SEGMENT.id, 'VIP contacts'));
  });

  it('starts a delete via onDelete - NO confirm dialog', async () => {
    const user = userEvent.setup();
    const onDelete = vi.fn();
    render(
      <ManageSegmentsDialog
        open
        onOpenChange={vi.fn()}
        segments={[SEGMENT]}
        filterFields={FIELDS}
        onRename={vi.fn()}
        onEditFilter={vi.fn()}
        deletingId={null}
        onDelete={onDelete}
      />,
    );

    await user.click(screen.getByRole('button', { name: `Delete ${SEGMENT.name}` }));

    // No AlertDialog anywhere - the grace window IS the confirmation.
    expect(screen.queryByText(/cannot be undone/i)).not.toBeInTheDocument();
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
    expect(onDelete).toHaveBeenCalledWith(SEGMENT);
  });

  it('disables every OTHER row Delete while one segment is counting down (review round 2, blocker 2)', () => {
    render(
      <ManageSegmentsDialog
        open
        onOpenChange={vi.fn()}
        segments={[SEGMENT, SEGMENT_2]}
        filterFields={FIELDS}
        onRename={vi.fn()}
        onEditFilter={vi.fn()}
        deletingId={SEGMENT.id}
        onDelete={vi.fn()}
      />,
    );

    expect(screen.getByRole('button', { name: `Delete ${SEGMENT.name}` })).toBeDisabled();
    expect(screen.getByRole('button', { name: `Delete ${SEGMENT_2.name}` })).toBeDisabled();
  });

  it('re-enables every row once the countdown settles (deletingId back to null)', () => {
    const { rerender } = render(
      <ManageSegmentsDialog
        open
        onOpenChange={vi.fn()}
        segments={[SEGMENT, SEGMENT_2]}
        filterFields={FIELDS}
        onRename={vi.fn()}
        onEditFilter={vi.fn()}
        deletingId={SEGMENT.id}
        onDelete={vi.fn()}
      />,
    );
    expect(screen.getByRole('button', { name: `Delete ${SEGMENT_2.name}` })).toBeDisabled();

    rerender(
      <ManageSegmentsDialog
        open
        onOpenChange={vi.fn()}
        segments={[SEGMENT, SEGMENT_2]}
        filterFields={FIELDS}
        onRename={vi.fn()}
        onEditFilter={vi.fn()}
        deletingId={null}
        onDelete={vi.fn()}
      />,
    );
    expect(screen.getByRole('button', { name: `Delete ${SEGMENT_2.name}` })).not.toBeDisabled();
  });
});
