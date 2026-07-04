/**
 * Review-config Details tab (AC-06-63) — the only-valid-option pickers:
 * scoreFieldKey lists ONLY numeric fields of the review form, the 4 status maps
 * list ONLY the submission form's scoped statuses, and a review form with no
 * numeric field surfaces the warning + disables the score picker (AC-06-55).
 */
import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { ReviewConfigMeta } from '@/types/review';
import { DetailsTab, type DetailsValues } from './details-tab';

vi.mock('next-auth/react', () => ({
  useSession: () => ({ data: { user: { timezone: 'UTC' } } }),
}));

const META: ReviewConfigMeta = {
  submissionStatuses: [
    { id: 'st-review', label: 'In review', color: '#f59e0b' },
    { id: 'st-accepted', label: 'Accepted', color: '#22c55e' },
  ],
  numericFields: [{ key: 'overall', label: 'Overall score' }],
  submissionFacts: [],
};

const VALUES: DetailsValues = {
  name: 'Peer review',
  formId: 'form-a',
  reviewFormId: 'form-b',
  requiredReviewCount: 2,
  scoreFieldKey: null,
  windowStart: null,
  windowEnd: null,
  reviewStartStatusId: null,
  revisionsStatusId: null,
  acceptedStatusId: null,
  rejectedStatusId: null,
  isActive: true,
};

const FORM_OPTIONS = [
  { value: 'form-a', label: 'Abstract form' },
  { value: 'form-b', label: 'Rubric form' },
];

function setup(meta: ReviewConfigMeta = META, values: DetailsValues = VALUES) {
  const onChange = vi.fn();
  render(
    <DetailsTab
      values={values}
      onChange={onChange}
      editing
      meta={meta}
      formOptions={FORM_OPTIONS}
    />,
  );
  return { onChange };
}

describe('DetailsTab pickers (AC-06-55)', () => {
  it('score field lists ONLY numeric fields of the review form', () => {
    setup();
    fireEvent.click(screen.getByRole('combobox', { name: 'Score field' }));
    const listbox = screen.getByRole('listbox');
    expect(within(listbox).getByText('Overall score')).toBeInTheDocument();
    // A non-numeric answer key must never be offered.
    expect(within(listbox).queryByText('Track')).not.toBeInTheDocument();
  });

  it('status mapping lists ONLY the submission form scoped statuses', () => {
    setup();
    fireEvent.click(screen.getByRole('combobox', { name: 'Review start status' }));
    const listbox = screen.getByRole('listbox');
    expect(within(listbox).getByText('In review')).toBeInTheDocument();
    expect(within(listbox).getByText('Accepted')).toBeInTheDocument();
    // Draft is not in the meta → must not appear.
    expect(within(listbox).queryByText('Draft')).not.toBeInTheDocument();
  });

  it('warns and disables the score picker when the review form has no numeric field', () => {
    const meta: ReviewConfigMeta = { ...META, numericFields: [] };
    setup(meta);
    expect(screen.getByText(/no numeric field/i)).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: 'Score field' })).toBeDisabled();
  });

  it('selecting a status fires onChange with the chosen id', () => {
    const { onChange } = setup();
    fireEvent.click(screen.getByRole('combobox', { name: 'Accepted status' }));
    fireEvent.click(within(screen.getByRole('listbox')).getByText('Accepted'));
    expect(onChange).toHaveBeenCalledWith({ acceptedStatusId: 'st-accepted' });
  });
});
