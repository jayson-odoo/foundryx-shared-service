import { describe, expect, it, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { ApiError } from '@/lib/api-client';
import type { LeadField, LeadSourceItem } from '@/types/lead-capture';
import { MapFieldsDialog } from './map-fields-dialog';

const formQuestions = vi.fn();
const saveFieldMap = vi.fn();
vi.mock('@/services/lead-capture-service', () => ({
  leadCaptureService: {
    formQuestions: (...a: unknown[]) => formQuestions(...a),
    saveFieldMap: (...a: unknown[]) => saveFieldMap(...a),
  },
}));
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const fields: LeadField[] = [
  { key: 'name', label: 'Name', type: 'name' },
  { key: 'budget', label: 'Budget', type: 'text' },
  { key: 'notes', label: 'Lead notes', type: 'notes' },
];

const source: LeadSourceItem = {
  id: 'src1',
  platform: 'facebook',
  name: 'Facebook',
  status: 'LIVE',
  pageId: '1',
  pageName: 'Sample Home Page',
  formsMode: 'all',
  needsMapping: [],
  fieldMap: { '222': { what_is_your_budget: 'budget' } },
  lastLeadAt: null,
  createdAt: '2026-11-17T00:00:00Z',
};

const target = { sourceId: 'src1', formId: '222', formName: 'Show unit enquiry' };

beforeEach(() => {
  vi.clearAllMocks();
  formQuestions.mockResolvedValue({
    formId: '222',
    formName: 'Show unit enquiry',
    data: [
      { key: 'full_name', label: 'Full name', type: 'FULL_NAME' },
      { key: 'what_is_your_budget', label: 'What is your budget?', type: 'CUSTOM' },
      { key: 'best_time', label: 'Best time to call', type: 'CUSTOM' },
    ],
  });
  saveFieldMap.mockResolvedValue(source);
});

describe('MapFieldsDialog', () => {
  it('shows each question with its current field and saves every question', async () => {
    const onSaved = vi.fn();
    const onClose = vi.fn();
    render(
      <MapFieldsDialog
        target={target}
        sources={[source]}
        fields={fields}
        canManage
        onClose={onClose}
        onSaved={onSaved}
      />,
    );
    await waitFor(() => expect(screen.getByText('What is your budget?')).toBeInTheDocument());
    expect(formQuestions).toHaveBeenCalledWith('src1', '222');
    expect(screen.getByRole('combobox', { name: 'Full name' })).toHaveTextContent('Name (automatic)');
    expect(screen.getByRole('combobox', { name: 'What is your budget?' })).toHaveTextContent('Budget');
    expect(screen.getByRole('combobox', { name: 'Best time to call' })).toHaveTextContent('Leave in lead notes');

    fireEvent.click(screen.getByRole('button', { name: 'Save map' }));
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    expect(saveFieldMap).toHaveBeenCalledWith('src1', '222', {
      full_name: null,
      what_is_your_budget: 'budget',
      best_time: null,
    });
    expect(onClose).toHaveBeenCalled();
  });

  it("shows Meta's reason with Try again when the questions cannot be read", async () => {
    formQuestions.mockRejectedValueOnce(
      new ApiError('x', 409, null, { code: 'meta_refused', message: 'This Page has not given Leads Access yet.' }),
    );
    render(
      <MapFieldsDialog target={target} sources={[source]} fields={fields} canManage onClose={vi.fn()} onSaved={vi.fn()} />,
    );
    await waitFor(() => expect(screen.getByText('This Page has not given Leads Access yet.')).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
    await waitFor(() => expect(screen.getByText('Best time to call')).toBeInTheDocument());
    expect(formQuestions).toHaveBeenCalledTimes(2);
  });

  it('All forms lists its stored lines without calling Meta, and saves them', async () => {
    const allForms: LeadSourceItem = { ...source, fieldMap: { '*': { what_is_your_budget: 'budget', full_name: 'name' } } };
    const onSaved = vi.fn();
    render(
      <MapFieldsDialog
        target={{ sourceId: 'src1', formId: '*', formName: 'All forms' }}
        sources={[allForms]}
        fields={fields}
        canManage
        onClose={vi.fn()}
        onSaved={onSaved}
      />,
    );
    await waitFor(() => expect(screen.getByRole('combobox', { name: 'what_is_your_budget' })).toHaveTextContent('Budget'));
    expect(screen.getByRole('combobox', { name: 'full_name' })).toHaveTextContent('Name');
    expect(formQuestions).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Save map' }));
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    expect(saveFieldMap).toHaveBeenCalledWith('src1', '*', { what_is_your_budget: 'budget', full_name: 'name' });
  });
});
