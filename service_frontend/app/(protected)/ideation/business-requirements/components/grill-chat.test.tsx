import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { GrillField, GrillMessage } from '@/types/grill';
import { GrillChat } from './grill-chat';

const FIELDS: GrillField[] = [
  { key: 'problem_statement', label: 'Problem statement' },
  { key: 'business_goal', label: 'Business goal' },
  { key: 'success_metric', label: 'Success metric' },
];

function renderChat(overrides: Partial<React.ComponentProps<typeof GrillChat>> = {}) {
  const onSend = vi.fn();
  const onGenerate = vi.fn();
  const props: React.ComponentProps<typeof GrillChat> = {
    messages: [],
    fields: FIELDS,
    coveredFields: [],
    missingFields: FIELDS,
    sending: false,
    generating: false,
    disabled: false,
    error: null,
    onSend,
    onGenerate,
    ...overrides,
  };
  render(<GrillChat {...props} />);
  return { onSend, onGenerate };
}

describe('GrillChat (AC-BI-29)', () => {
  it('shows the coverage indicator "N of M captured · missing …"', () => {
    renderChat({ coveredFields: ['problem_statement'], missingFields: FIELDS.slice(1) });
    expect(screen.getByText('1 of 3 captured')).toBeInTheDocument();
    expect(screen.getByText(/Business goal, Success metric/)).toBeInTheDocument();
  });

  it('reports full coverage when nothing is missing', () => {
    renderChat({ coveredFields: FIELDS.map((f) => f.key), missingFields: [] });
    expect(screen.getByText('3 of 3 captured')).toBeInTheDocument();
    expect(screen.getByText('All fields captured')).toBeInTheDocument();
  });

  it('renders user turns and assistant turns', () => {
    const messages: GrillMessage[] = [
      { id: 'u', role: 'user', content: 'CS cannot export', coveredFields: [], createdAt: 'x' },
      { id: 'a', role: 'assistant', content: 'Who are the users?', coveredFields: [], createdAt: 'x' },
    ];
    renderChat({ messages });
    expect(screen.getByText('CS cannot export')).toBeInTheDocument();
    expect(screen.getByText('Who are the users?')).toBeInTheDocument();
  });

  it('sends a typed message via the Send button', () => {
    const { onSend } = renderChat();
    fireEvent.change(screen.getByPlaceholderText('Message the grill'), {
      target: { value: 'It is about exports' },
    });
    fireEvent.click(screen.getByRole('button', { name: /send/i }));
    expect(onSend).toHaveBeenCalledWith('It is about exports');
  });

  it('keeps Generate enabled even with coverage incomplete (AC-BI-22)', () => {
    const { onGenerate } = renderChat({ coveredFields: [], missingFields: FIELDS });
    const generate = screen.getByRole('button', { name: /generate/i });
    expect(generate).not.toBeDisabled();
    fireEvent.click(generate);
    expect(onGenerate).toHaveBeenCalled();
  });

  it('shows a thinking indicator while a turn is in flight', () => {
    renderChat({ sending: true });
    expect(screen.getByText('Thinking…')).toBeInTheDocument();
  });
});
