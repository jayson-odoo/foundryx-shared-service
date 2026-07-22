/**
 * FormRenderer (plan sprint-3/01, D6/D7/D14/D18) — per-type render + inline
 * validation messages, live conditional show/hide, live computed update, paged
 * Next-blocking, submit returning only visible answers, read-mode value
 * rendering, signature canvas mount + clear, and server-error page jump.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { useState } from 'react';
import { beforeAll, describe, expect, it, vi } from 'vitest';
import { FormRenderer } from './form-renderer';
import type { FormAnswers, FormDocument, FormField } from '@/types/forms';
import { FORM_SCHEMA_VERSION } from '@/types/forms';

// jsdom has no canvas — stub getContext so the SignaturePad mounts/clears.
beforeAll(() => {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (HTMLCanvasElement.prototype as any).getContext = vi.fn(() => ({
    setTransform: vi.fn(),
    beginPath: vi.fn(),
    moveTo: vi.fn(),
    lineTo: vi.fn(),
    stroke: vi.fn(),
    clearRect: vi.fn(),
    drawImage: vi.fn(),
  }));
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (HTMLCanvasElement.prototype as any).toDataURL = vi.fn(() => 'data:image/png;base64,AAAA');
});

function field(over: Partial<FormField> & Pick<FormField, 'type'>): FormField {
  return { id: `fld_${over.key ?? over.type}`, label: over.label ?? over.key ?? over.type, ...over };
}

function single(fields: FormField[]): FormDocument {
  return { schemaVersion: FORM_SCHEMA_VERSION, pages: [{ id: 'p0', sections: [{ id: 's0', fields }] }] };
}

/** Controlled host so answers flow back into the renderer (live conditions). */
function Harness({
  definition,
  initial = {},
  onSubmit,
  paged,
}: {
  definition: FormDocument;
  initial?: FormAnswers;
  onSubmit?: (visible: FormAnswers) => void;
  paged?: boolean;
}) {
  const [answers, setAnswers] = useState<FormAnswers>(initial);
  return (
    <FormRenderer
      definition={definition}
      mode="fill"
      paged={paged}
      answers={answers}
      onChange={setAnswers}
      onSubmit={onSubmit}
    />
  );
}

describe('per-type render', () => {
  it('renders a text input with its label', () => {
    render(<Harness definition={single([field({ type: 'text', key: 'name', label: 'Your name' })])} />);
    expect(screen.getByText('Your name')).toBeInTheDocument();
    expect(screen.getByLabelText('Your name')).toHaveAttribute('type', 'text');
  });

  it('renders helpText from the doc only', () => {
    render(
      <Harness
        definition={single([field({ type: 'text', key: 't', label: 'T', helpText: 'A hint.' })])}
      />,
    );
    expect(screen.getByText('A hint.')).toBeInTheDocument();
  });
});

describe('required validation message on submit', () => {
  it('shows the inline message and blocks submit', () => {
    const onSubmit = vi.fn();
    render(
      <Harness
        definition={single([field({ type: 'text', key: 'name', label: 'Name', required: true })])}
        onSubmit={onSubmit}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Submit' }));
    expect(screen.getByRole('alert')).toHaveTextContent('required');
    expect(onSubmit).not.toHaveBeenCalled();
  });
});

describe('conditional show/hide is live', () => {
  const def = single([
    field({ type: 'yesno', key: 'subscribe', label: 'Subscribe?' }),
    field({
      type: 'email',
      key: 'newsletterEmail',
      label: 'Email',
      conditionsJson: {
        kind: 'group',
        combinator: 'and',
        rules: [{ kind: 'condition', fact: 'answers.subscribe', operator: 'is_true', value: true, valueKind: 'literal' }],
      },
    }),
  ]);

  it('reveals the dependent field when the trigger flips', () => {
    render(<Harness definition={def} />);
    expect(screen.queryByLabelText('Email')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Yes' }));
    expect(screen.getByLabelText('Email')).toBeInTheDocument();
  });
});

describe('computed live update', () => {
  it('recomputes as inputs change', () => {
    const def = single([
      field({ type: 'number', key: 'qty', label: 'Qty' }),
      field({ type: 'number', key: 'price', label: 'Price' }),
      field({ type: 'computed', key: 'total', label: 'Total', computed: { expression: 'qty * price' } }),
    ]);
    render(<Harness definition={def} />);
    fireEvent.change(screen.getByLabelText('Qty'), { target: { value: '3' } });
    fireEvent.change(screen.getByLabelText('Price'), { target: { value: '4' } });
    expect(document.querySelector('[data-slot="computed-value"]')).toHaveTextContent('12');
  });
});

describe('paged wizard', () => {
  const def: FormDocument = {
    schemaVersion: FORM_SCHEMA_VERSION,
    pages: [
      { id: 'p0', sections: [{ id: 's0', fields: [field({ type: 'text', key: 'a', label: 'A', required: true })] }] },
      { id: 'p1', sections: [{ id: 's1', fields: [field({ type: 'text', key: 'b', label: 'B' })] }] },
    ],
  };

  it('blocks Next on an invalid page', () => {
    render(<Harness definition={def} paged />);
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    expect(screen.getByRole('alert')).toHaveTextContent('required');
    expect(screen.queryByLabelText('B')).not.toBeInTheDocument();
  });

  it('advances once the page is valid', () => {
    render(<Harness definition={def} paged />);
    // Required label includes the aria-hidden "*" marker — match by id.
    fireEvent.change(document.getElementById('ff-a')!, { target: { value: 'x' } });
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    expect(screen.getByLabelText('B')).toBeInTheDocument();
  });
});

describe('submit returns only visible answers', () => {
  it('drops hidden-field answers', async () => {
    const onSubmit = vi.fn();
    const def = single([
      field({ type: 'yesno', key: 'subscribe', label: 'Subscribe?' }),
      field({
        type: 'text',
        key: 'hiddenWhenNo',
        label: 'Detail',
        conditionsJson: {
          kind: 'group',
          combinator: 'and',
          rules: [{ kind: 'condition', fact: 'answers.subscribe', operator: 'is_true', value: true, valueKind: 'literal' }],
        },
      }),
    ]);
    render(<Harness definition={def} initial={{ subscribe: false, hiddenWhenNo: 'leaked' }} onSubmit={onSubmit} />);
    fireEvent.click(screen.getByRole('button', { name: 'Submit' }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    expect(onSubmit.mock.calls[0][0]).toEqual({ subscribe: false });
  });
});

describe('read mode', () => {
  it('renders formatted values, not inputs', () => {
    const def = single([
      field({ type: 'yesno', key: 'agree', label: 'Agree' }),
      field({
        type: 'select',
        key: 'plan',
        label: 'Plan',
        options: { kind: 'static', items: [{ value: 'pro', label: 'Pro plan' }] },
      }),
    ]);
    render(
      <FormRenderer definition={def} mode="read" answers={{ agree: true, plan: 'pro' }} />,
    );
    expect(screen.getByText('Yes')).toBeInTheDocument();
    expect(screen.getByText('Pro plan')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Yes' })).not.toBeInTheDocument();
  });
});

describe('signature pad', () => {
  it('mounts a canvas and clears', () => {
    const def = single([field({ type: 'signature', key: 'sig', label: 'Sign here' })]);
    render(<Harness definition={def} initial={{ sig: 'data:image/png;base64,XXX' }} />);
    const canvas = screen.getByRole('img', { name: 'Sign here' });
    expect(canvas.tagName).toBe('CANVAS');
    const clear = screen.getByRole('button', { name: 'Clear' });
    expect(clear).toBeEnabled();
    fireEvent.click(clear);
  });
});

describe('server errors jump to the right page', () => {
  it('moves the wizard to the errored field page', () => {
    const def: FormDocument = {
      schemaVersion: FORM_SCHEMA_VERSION,
      pages: [
        { id: 'p0', sections: [{ id: 's0', fields: [field({ type: 'text', key: 'a', label: 'A' })] }] },
        { id: 'p1', sections: [{ id: 's1', fields: [field({ type: 'text', key: 'b', label: 'B' })] }] },
      ],
    };
    render(
      <FormRenderer
        definition={def}
        mode="fill"
        paged
        answers={{ a: 'x' }}
        errors={{ b: 'Server says no.' }}
      />,
    );
    // Jumped to page 2 → field B visible with its server error.
    expect(screen.getByLabelText('B')).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('Server says no.');
  });
});

describe('table block (sprint-3/02)', () => {
  it('computes per-row amount live and totals the column', () => {
    const def = single([
      field({
        type: 'table',
        key: 'po',
        label: 'PO Lines',
        table: {
          showRowNumbers: true,
          columns: [
            { id: 'c1', type: 'text', key: 'item', label: 'Item' },
            { id: 'c2', type: 'number', key: 'qty', label: 'Qty' },
            { id: 'c3', type: 'number', key: 'price', label: 'Price' },
            { id: 'c4', type: 'computed', key: 'amount', label: 'Amount', computed: { expression: 'qty * price' }, summarize: 'sum' },
          ],
        },
      }),
    ]);
    render(
      <Harness
        definition={def}
        initial={{ po: [{ item: 'A', qty: 2, price: 3, amount: 6 }, { item: 'B', qty: 4, price: 5, amount: 20 }] }}
      />,
    );
    const cells = document.querySelectorAll('[data-slot="table-computed"]');
    expect(cells[0]).toHaveTextContent('6');
    expect(cells[1]).toHaveTextContent('20');
    expect(screen.getByText('26')).toBeInTheDocument(); // footer total
  });
});

describe('flat mode (AC-BI-29c)', () => {
  const doc: FormDocument = {
    schemaVersion: FORM_SCHEMA_VERSION,
    pages: [
      {
        id: 'p0',
        title: 'Business Requirement',
        sections: [
          {
            id: 's0',
            title: 'Requirement',
            description: 'Fill this in',
            fields: [field({ type: 'textarea', key: 'problem_statement', label: 'Problem statement' })],
          },
        ],
      },
    ],
  };

  it('shows page + section chrome by DEFAULT', () => {
    render(<Harness definition={doc} />);
    expect(screen.getByText('Business Requirement')).toBeInTheDocument();
    expect(screen.getByText('Requirement')).toBeInTheDocument();
    expect(screen.getByText('Fill this in')).toBeInTheDocument();
    expect(screen.getByText('Problem statement')).toBeInTheDocument();
  });

  it('OMITS page title + section title/description when flat, keeping the fields', () => {
    render(
      <FormRenderer definition={doc} mode="read" answers={{ problem_statement: 'Exports break' }} flat />,
    );
    expect(screen.queryByText('Business Requirement')).not.toBeInTheDocument();
    expect(screen.queryByText('Requirement')).not.toBeInTheDocument();
    expect(screen.queryByText('Fill this in')).not.toBeInTheDocument();
    // The field label + value still render — only the structural chrome is gone.
    expect(screen.getByText('Problem statement')).toBeInTheDocument();
    expect(screen.getByText('Exports break')).toBeInTheDocument();
  });
});
