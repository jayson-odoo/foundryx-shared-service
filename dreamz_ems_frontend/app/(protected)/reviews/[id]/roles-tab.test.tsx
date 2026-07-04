/**
 * Review-config Roles tab (AC-06-63) — role label is free text + capabilities
 * drive the editor (AC-06-54/28), the source SearchSelect swaps the sub-editor
 * (AC-06-55), and an unconfigured PERSONA role surfaces the warning (AC-06-55).
 */
import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { ReviewActorOptions } from '@/hooks/use-review-actor-options';
import type { ReviewRoleInput } from '@/types/review';
import type { RuleFact } from '@/types/rules';
import { RolesTab } from './roles-tab';

vi.mock('@/hooks/use-terminology', () => ({
  useTerminology: () => ({
    ready: true,
    label: (k: string) => (k === 'form' ? 'Submission' : k),
    labelPlural: (k: string) => k,
    t: (k: string) => k,
    refetch: () => Promise.resolve(),
  }),
}));

const ACTOR_OPTIONS: ReviewActorOptions = {
  users: [{ value: 'u1', label: 'Alice' }],
  profiles: [{ value: 'p1', label: 'Bob' }],
  personas: [{ value: 'persona-1', label: 'Reviewer persona' }],
  staffRoles: [{ value: 'role-1', label: 'Coordinator' }],
  loading: false,
};

const FACTS: RuleFact[] = [
  {
    key: 'answers.track',
    label: 'Track',
    type: 'enum',
    source: 'submission',
    sourceLabel: 'Submission answers',
    options: [{ value: 'ai', label: 'AI' }],
  },
];

function role(overrides: Partial<ReviewRoleInput> = {}): ReviewRoleInput {
  return {
    key: 'role_1',
    label: '',
    canSubmit: false,
    canReview: false,
    canDecide: false,
    actorSource: 'EXPLICIT',
    actorIdentityKind: 'profile',
    boundPersonaId: null,
    boundStaffRoleId: null,
    conditionsJson: null,
    sortOrder: 0,
    actors: [],
    ...overrides,
  };
}

function setup(roles: ReviewRoleInput[], emsActive = true) {
  const onChange = vi.fn();
  render(
    <RolesTab
      roles={roles}
      onChange={onChange}
      editing
      emsActive={emsActive}
      facts={FACTS}
      actorOptions={ACTOR_OPTIONS}
    />,
  );
  return { onChange };
}

describe('RolesTab (AC-06-54/55)', () => {
  it('label is free text (AC-06-54) — typing fires onChange with the raw value', () => {
    const { onChange } = setup([role()]);
    fireEvent.change(screen.getByRole('textbox', { name: 'Role label' }), {
      target: { value: 'Chairperson' },
    });
    expect(onChange).toHaveBeenCalledWith([expect.objectContaining({ label: 'Chairperson' })]);
  });

  it('capabilities drive the editor — toggling Can review fires onChange', () => {
    const { onChange } = setup([role()]);
    fireEvent.click(screen.getByLabelText('Can review'));
    expect(onChange).toHaveBeenCalledWith([expect.objectContaining({ canReview: true })]);
  });

  it('an unconfigured PERSONA role shows the warning (AC-06-55)', () => {
    setup([role({ actorSource: 'PERSONA', actorIdentityKind: 'profile', boundPersonaId: null })]);
    expect(screen.getByRole('alert')).toHaveTextContent(/choose a persona/i);
  });

  it('a PERSONA role with a bound persona shows NO warning', () => {
    setup([
      role({ actorSource: 'PERSONA', actorIdentityKind: 'profile', boundPersonaId: 'persona-1' }),
    ]);
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('source switch swaps the sub-editor: PERSONA shows the persona picker, RULE the rule builder', () => {
    // PERSONA → a "Persona" labelled SearchSelect.
    const { rerender } = render(
      <RolesTab
        roles={[role({ actorSource: 'PERSONA', boundPersonaId: 'persona-1' })]}
        onChange={vi.fn()}
        editing
        emsActive
        facts={FACTS}
        actorOptions={ACTOR_OPTIONS}
      />,
    );
    expect(screen.getByRole('combobox', { name: 'Bound persona' })).toBeInTheDocument();
    expect(screen.queryByText('Match rule')).not.toBeInTheDocument();

    // RULE → the rule builder ("Match rule" label, no persona picker).
    rerender(
      <RolesTab
        roles={[role({ actorSource: 'RULE' })]}
        onChange={vi.fn()}
        editing
        emsActive
        facts={FACTS}
        actorOptions={ACTOR_OPTIONS}
      />,
    );
    expect(screen.getByText('Match rule')).toBeInTheDocument();
    expect(screen.queryByRole('combobox', { name: 'Bound persona' })).not.toBeInTheDocument();
  });

  it('hides PERSONA / profile sources when the ems module is inactive (foolproof-UI)', () => {
    setup([role({ actorSource: 'EXPLICIT', actorIdentityKind: 'user' })], false);
    fireEvent.click(screen.getByRole('combobox', { name: 'Actor source' }));
    const listbox = screen.getByRole('listbox');
    expect(within(listbox).queryByText('Persona')).not.toBeInTheDocument();
    expect(within(listbox).getByText('Staff role')).toBeInTheDocument();
  });
});
