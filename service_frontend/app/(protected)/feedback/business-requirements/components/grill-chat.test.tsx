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
  const props: React.ComponentProps<typeof GrillChat> = {
    messages: [],
    fields: FIELDS,
    coveredFields: [],
    capturedSummary: {},
    missingFields: FIELDS,
    sending: false,
    generating: false,
    disabled: false,
    error: null,
    onSend,
    ...overrides,
  };
  render(<GrillChat {...props} />);
  return { onSend };
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

  it('has NO explicit Generate button (AC-BI-29c - generation fires from the signal)', () => {
    renderChat({ coveredFields: [], missingFields: FIELDS });
    expect(screen.queryByRole('button', { name: /generate/i })).not.toBeInTheDocument();
    // Only the Send action is offered in the composer.
    expect(screen.getByRole('button', { name: /send/i })).toBeInTheDocument();
  });

  it('shows a generating status while a Generate is in flight (AC-BI-29c)', () => {
    renderChat({ generating: true });
    expect(screen.getByText(/Generating the requirement/i)).toBeInTheDocument();
  });

  it('shows a thinking indicator while a turn is in flight', () => {
    renderChat({ sending: true });
    expect(screen.getByText('Thinking…')).toBeInTheDocument();
  });

  it('renders the running captured summary values per field (AC-BI-24c)', () => {
    renderChat({
      coveredFields: ['problem_statement'],
      capturedSummary: { problem_statement: 'Exports time out on big accounts' },
    });
    // Each target field appears as a summary label (labels also head the panel).
    expect(screen.getAllByText('Problem statement').length).toBeGreaterThan(0);
    // The captured value is shown for the grounded field…
    expect(screen.getByText('Exports time out on big accounts')).toBeInTheDocument();
    // …and an em-dash placeholder for the two not-yet-captured fields.
    expect(screen.getAllByText('-')).toHaveLength(2);
  });
});
