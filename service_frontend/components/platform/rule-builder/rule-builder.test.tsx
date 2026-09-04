/**
 * RuleBuilder (sprint-2/02) - condition-tree builder over the whitelisted
 * fact registry. Sibling of filter-builder (D9): per-type operators,
 * cross-fact compare toggle, nested AND/OR groups, stale-fact chips.
 */
import { fireEvent, render as rtlRender, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { RuleFact, RuleGroup } from '@/types/rules';
import { TooltipsProvider } from '@/providers/tooltips-provider';
import { RuleBuilder } from './rule-builder';

/**
 * `tooltip.tsx` is a bare Radix Root since AC-DLA-16 (the one app-wide
 * provider lives in `TooltipsProvider`, mounted once in `app/layout.tsx`) -
 * `RuleBuilder` renders tooltips on its stale-fact chips, so every render in
 * this file needs one in its tree too.
 */
function render(ui: React.ReactElement) {
  return rtlRender(<TooltipsProvider>{ui}</TooltipsProvider>);
}

const FACTS: RuleFact[] = [
  {
    key: 'actor.email',
    label: 'Email',
    type: 'string',
    source: 'actor',
    sourceLabel: 'Acting user',
  },
  {
    key: 'actor.createdAt',
    label: 'Member since',
    type: 'date',
    source: 'actor',
    sourceLabel: 'Acting user',
  },
  {
    key: 'actor.roles',
    label: 'Roles',
    type: 'list',
    source: 'actor',
    sourceLabel: 'Acting user',
    options: [
      { value: 'admin', label: 'Admin' },
      { value: 'agent', label: 'Agent' },
    ],
  },
  {
    key: 'record.isPlatform',
    label: 'Is platform',
    type: 'boolean',
    source: 'record:tenant',
    sourceLabel: 'Tenant record',
  },
  {
    key: 'record.createdAt',
    label: 'Created at',
    type: 'date',
    source: 'record:tenant',
    sourceLabel: 'Tenant record',
  },
  {
    key: 'record.userCount',
    label: 'User count',
    type: 'number',
    source: 'record:tenant',
    sourceLabel: 'Tenant record',
  },
];

const TREE: RuleGroup = {
  kind: 'group',
  combinator: 'and',
  rules: [
    {
      kind: 'condition',
      fact: 'record.isPlatform',
      operator: 'is_false',
      valueKind: 'literal',
      value: null,
    },
  ],
};

describe('RuleBuilder', () => {
  it('renders an existing tree and groups the fact picker by source', () => {
    render(<RuleBuilder facts={FACTS} value={TREE} onChange={vi.fn()} />);

    // The existing condition row shows its fact + boolean operator.
    expect(screen.getByText('Is platform')).toBeInTheDocument();
    expect(screen.getByText('is no')).toBeInTheDocument();

    // Fact picker groups by sourceLabel.
    fireEvent.click(screen.getByRole('combobox', { name: /fact/i }));
    expect(screen.getByText('Acting user')).toBeInTheDocument();
    expect(screen.getByText('Tenant record')).toBeInTheDocument();
  });

  it('offers operators per the selected fact type', () => {
    const onChange = vi.fn();
    render(<RuleBuilder facts={FACTS} value={TREE} onChange={onChange} />);

    // Switch the fact to a number → operator menu must hold number ops.
    fireEvent.click(screen.getByRole('combobox', { name: /fact/i }));
    fireEvent.click(screen.getByText('User count'));

    const operator = screen.getByRole('combobox', { name: /operator/i });
    fireEvent.click(operator);
    expect(screen.getByRole('option', { name: 'between' })).toBeInTheDocument();
    expect(
      screen.queryByRole('option', { name: 'contains' }),
    ).not.toBeInTheDocument();
  });

  it('emits the serialized tree on edit', () => {
    const onChange = vi.fn();
    render(<RuleBuilder facts={FACTS} value={TREE} onChange={onChange} />);

    fireEvent.click(screen.getByRole('button', { name: /add condition/i }));
    const emitted = onChange.mock.lastCall?.[0] as RuleGroup;
    expect(emitted.kind).toBe('group');
    expect(emitted.rules).toHaveLength(2);
    expect(emitted.rules[0]).toMatchObject({
      fact: 'record.isPlatform',
      operator: 'is_false',
    });
  });

  it('removes a nested group (with its contents) from the tree', () => {
    const onChange = vi.fn();
    const tree: RuleGroup = {
      kind: 'group',
      combinator: 'and',
      rules: [
        {
          kind: 'condition',
          fact: 'record.isPlatform',
          operator: 'is_false',
          valueKind: 'literal',
          value: null,
        },
        {
          kind: 'group',
          combinator: 'or',
          rules: [
            {
              kind: 'condition',
              fact: 'actor.email',
              operator: 'eq',
              valueKind: 'literal',
              value: 'x',
            },
          ],
        },
      ],
    };
    render(<RuleBuilder facts={FACTS} value={tree} onChange={onChange} />);

    fireEvent.click(screen.getByRole('button', { name: /remove group/i }));
    const emitted = onChange.mock.lastCall?.[0] as RuleGroup;
    expect(emitted.rules).toHaveLength(1);
    expect(emitted.rules[0]).toMatchObject({
      kind: 'condition',
      fact: 'record.isPlatform',
    });
  });

  it('emits null when the last condition is removed (unconditional)', () => {
    const onChange = vi.fn();
    render(<RuleBuilder facts={FACTS} value={TREE} onChange={onChange} />);

    fireEvent.click(screen.getByRole('button', { name: /remove condition/i }));
    expect(onChange).toHaveBeenLastCalledWith(null);
  });

  it('cross-fact toggle limits the RHS picker to same-type facts', () => {
    const onChange = vi.fn();
    const tree: RuleGroup = {
      kind: 'group',
      combinator: 'and',
      rules: [
        {
          kind: 'condition',
          fact: 'record.createdAt',
          operator: 'before',
          valueKind: 'literal',
          value: '',
        },
      ],
    };
    render(<RuleBuilder facts={FACTS} value={tree} onChange={onChange} />);

    fireEvent.click(screen.getByRole('button', { name: /compare to field/i }));

    const rhs = screen.getByRole('combobox', { name: /compare fact/i });
    fireEvent.click(rhs);
    const listbox = screen.getByRole('listbox');
    // Same-type (date) facts, excluding the LHS fact itself.
    expect(within(listbox).getByText('Member since')).toBeInTheDocument();
    expect(within(listbox).queryByText('Created at')).not.toBeInTheDocument();
    expect(within(listbox).queryByText('Email')).not.toBeInTheDocument();
    expect(within(listbox).queryByText('User count')).not.toBeInTheDocument();
  });

  it('hides the cross-fact toggle for non-scalar operators', () => {
    const tree: RuleGroup = {
      kind: 'group',
      combinator: 'and',
      rules: [
        {
          kind: 'condition',
          fact: 'actor.roles',
          operator: 'contains_any',
          valueKind: 'literal',
          value: [],
        },
      ],
    };
    render(<RuleBuilder facts={FACTS} value={tree} onChange={vi.fn()} />);
    expect(
      screen.queryByRole('button', { name: /compare to field/i }),
    ).not.toBeInTheDocument();
  });

  it('flags stale facts with an unknown-field chip and a warning banner', () => {
    const tree: RuleGroup = {
      kind: 'group',
      combinator: 'and',
      rules: [
        {
          kind: 'condition',
          fact: 'record.ghost',
          operator: 'eq',
          valueKind: 'literal',
          value: 'x',
        },
      ],
    };
    render(<RuleBuilder facts={FACTS} value={tree} onChange={vi.fn()} />);

    expect(screen.getByText(/unknown field/i)).toBeInTheDocument();
    expect(screen.getByText(/no longer exist/i)).toBeInTheDocument();
  });

  it('disabled mode renders read-only', () => {
    render(
      <RuleBuilder facts={FACTS} value={TREE} onChange={vi.fn()} disabled />,
    );
    expect(
      screen.queryByRole('button', { name: /add condition/i }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: /fact/i })).toBeDisabled();
  });
});
