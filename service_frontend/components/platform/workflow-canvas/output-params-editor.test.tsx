/**
 * OutputParamsEditor (plan sprint-4/17 AC-OA-20) - the AI Agent action's
 * structured-output-schema editor. Exported directly from
 * node-config-drawer.tsx for isolated testing (see node-config-drawer test
 * for the full-drawer field-path coverage).
 */
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { OutputParamsEditor } from './node-config-drawer';
import type { WorkflowAiOutputParam } from '@/types/workflows';

describe('OutputParamsEditor', () => {
  it('renders a row per param', () => {
    const params: WorkflowAiOutputParam[] = [
      { key: 'intent', type: 'string', required: true },
      { key: 'confidence', type: 'number', required: false },
    ];
    render(<OutputParamsEditor params={params} editing={false} onChange={vi.fn()} />);
    expect(screen.getByDisplayValue('intent')).toBeInTheDocument();
    expect(screen.getByDisplayValue('confidence')).toBeInTheDocument();
  });

  it('shows the empty state when read-only with no params', () => {
    render(<OutputParamsEditor params={[]} editing={false} onChange={vi.fn()} />);
    expect(screen.getByText('No output parameters.')).toBeInTheDocument();
    expect(screen.queryByTestId('add-output-param')).not.toBeInTheDocument();
  });

  it('the add button appends a new required string row', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<OutputParamsEditor params={[]} editing onChange={onChange} />);

    await user.click(screen.getByTestId('add-output-param'));

    expect(onChange).toHaveBeenCalledWith([{ key: '', type: 'string', required: true }]);
  });

  it('the remove button deletes the row', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const params: WorkflowAiOutputParam[] = [
      { key: 'intent', type: 'string', required: true },
      { key: 'confidence', type: 'number', required: false },
    ];
    render(<OutputParamsEditor params={params} editing onChange={onChange} />);

    await user.click(screen.getByLabelText('Remove parameter 1'));

    expect(onChange).toHaveBeenCalledWith([{ key: 'confidence', type: 'number', required: false }]);
  });

  it('flags duplicate keys with aria-invalid on both key inputs', () => {
    const params: WorkflowAiOutputParam[] = [
      { key: 'intent', type: 'string', required: true },
      { key: 'intent', type: 'string', required: false },
      { key: 'urgency', type: 'string', required: false },
    ];
    render(<OutputParamsEditor params={params} editing onChange={vi.fn()} />);

    expect(screen.getByLabelText('Parameter 1 key')).toHaveAttribute('aria-invalid', 'true');
    expect(screen.getByLabelText('Parameter 2 key')).toHaveAttribute('aria-invalid', 'true');
    expect(screen.getByLabelText('Parameter 3 key')).toHaveAttribute('aria-invalid', 'false');
    expect(screen.getAllByText('Key must be unique.')).toHaveLength(2);
  });

  it('surfaces blank and invalid syntax keys clearly', () => {
    const params: WorkflowAiOutputParam[] = [
      { key: ' ', type: 'string', required: true },
      { key: 'intent-value', type: 'string', required: false },
    ];
    render(<OutputParamsEditor params={params} editing onChange={vi.fn()} />);

    expect(screen.getByLabelText('Parameter 1 key')).toHaveAttribute('aria-invalid', 'true');
    expect(screen.getByLabelText('Parameter 2 key')).toHaveAttribute('aria-invalid', 'true');
    expect(screen.getByText('Key is required.')).toBeInTheDocument();
    expect(screen.getByText(/Key must start with a letter/)).toBeInTheDocument();
  });

  it('surfaces invalid types from an older or malformed draft', () => {
    const params = [
      { key: 'intent', type: 'object', required: true },
    ] as unknown as WorkflowAiOutputParam[];
    render(<OutputParamsEditor params={params} editing={false} onChange={vi.fn()} />);

    expect(screen.getByText('Type must be string, number, or boolean.')).toBeInTheDocument();
  });

  it('editing a key/description/required field patches only that row', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const params: WorkflowAiOutputParam[] = [{ key: '', type: 'string', required: true }];
    render(<OutputParamsEditor params={params} editing onChange={onChange} />);

    await user.type(screen.getByLabelText('Parameter 1 key'), 'x');
    expect(onChange).toHaveBeenLastCalledWith([{ key: 'x', type: 'string', required: true }]);

    await user.click(screen.getByLabelText('Parameter 1 required'));
    expect(onChange).toHaveBeenLastCalledWith([{ key: '', type: 'string', required: false }]);
  });
});
