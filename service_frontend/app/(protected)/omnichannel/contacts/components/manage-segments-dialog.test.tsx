/**
 * "Manage segments" dialog (D-A2-3, AC-CTM-06/47) - the filter-edit popover
 * reuses the SAME `FilterBuilder` the list's Filters button opens, seeded via
 * `initialValue` (plan §"one filter-tree editor in the system"). Applying
 * without changing anything must round-trip the EXACT saved tree back out -
 * a silent reshape here would corrupt a segment nobody touched. Also covers
 * rename + delete, both permission-gated by the caller (`segments.manage`,
 * see `page.tsx`) before this dialog ever opens.
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
        onDelete={vi.fn()}
      />,
    );

    await user.click(screen.getByRole('button', { name: `Rename ${SEGMENT.name}` }));
    const input = screen.getByDisplayValue(SEGMENT.name);
    await user.clear(input);
    await user.type(input, 'VIP contacts{Enter}');

    await waitFor(() => expect(onRename).toHaveBeenCalledWith(SEGMENT.id, 'VIP contacts'));
  });

  it('confirms before deleting a segment', async () => {
    const user = userEvent.setup();
    const onDelete = vi.fn().mockResolvedValue(undefined);
    render(
      <ManageSegmentsDialog
        open
        onOpenChange={vi.fn()}
        segments={[SEGMENT]}
        filterFields={FIELDS}
        onRename={vi.fn()}
        onEditFilter={vi.fn()}
        onDelete={onDelete}
      />,
    );

    await user.click(screen.getByRole('button', { name: `Delete ${SEGMENT.name}` }));
    expect(screen.getByText(/cannot be undone/i)).toBeInTheDocument();
    expect(onDelete).not.toHaveBeenCalled();

    await user.click(screen.getByRole('button', { name: 'Delete' }));
    await waitFor(() => expect(onDelete).toHaveBeenCalledWith(SEGMENT.id));
  });
});
