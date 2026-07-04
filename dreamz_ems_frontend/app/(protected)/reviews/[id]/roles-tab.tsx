'use client';

/**
 * Roles tab of the Review-process detail form (AC-06-38/54/55/56). Each role is
 * free-form (the LABEL is per-config free text — AC-06-54) with capability
 * checkboxes that drive behavior, and a source SearchSelect whose choice swaps
 * the sub-editor (AC-06-55):
 *   RULE       → RuleBuilder over the submission form's answer facts + the
 *                candidate-actor pool (first-N by sort order).
 *   EXPLICIT   → a candidate-actor pool of the role's identity kind.
 *   PERSONA    → bind to one persona (profile-kind; ems only).
 *   STAFF_ROLE → bind to one staff role (user-kind).
 * A role whose source is unconfigured shows an inline WARNING (AC-06-55).
 * No procedural how-to copy; every dropdown is a SearchSelect (AC-06-56).
 */
import { Plus, Trash2, AlertTriangle } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Checkbox } from '@/components/ui/checkbox';
import { Badge } from '@/components/ui/badge';
import { MultiSelect } from '@/components/platform/multi-select';
import { RuleBuilder } from '@/components/platform/rule-builder';
import {
  SearchSelect,
  type SearchSelectOption,
} from '@/components/platform/search-select';
import { useTerminology } from '@/hooks/use-terminology';
import type { ReviewActorOptions } from '@/hooks/use-review-actor-options';
import type {
  ReviewActorIdentityKind,
  ReviewActorSource,
  ReviewRoleInput,
} from '@/types/review';
import type { RuleFact, RuleGroup } from '@/types/rules';

const IDENTITY_KIND_LABELS: Record<ReviewActorIdentityKind, string> = {
  user: 'Staff user',
  profile: 'Profile',
};

/** Source labels — generic nouns; PERSONA/profile only offered when ems active. */
function sourceOptions(emsActive: boolean): SearchSelectOption[] {
  const base: SearchSelectOption[] = [
    { value: 'EXPLICIT', label: 'Named people' },
    { value: 'RULE', label: 'Match a rule' },
    { value: 'STAFF_ROLE', label: 'Staff role' },
  ];
  if (emsActive) base.splice(2, 0, { value: 'PERSONA', label: 'Persona' });
  return base;
}

export interface RolesTabProps {
  roles: ReviewRoleInput[];
  onChange: (roles: ReviewRoleInput[]) => void;
  editing: boolean;
  emsActive: boolean;
  facts: RuleFact[];
  actorOptions: ReviewActorOptions;
}

function newRole(index: number): ReviewRoleInput {
  return {
    key: `role_${Date.now()}_${index}`,
    label: '',
    canSubmit: false,
    canReview: false,
    canDecide: false,
    actorSource: 'EXPLICIT',
    actorIdentityKind: 'profile',
    boundPersonaId: null,
    boundStaffRoleId: null,
    conditionsJson: null,
    sortOrder: index,
    actors: [],
  };
}

export function RolesTab({
  roles,
  onChange,
  editing,
  emsActive,
  facts,
  actorOptions,
}: RolesTabProps) {
  const update = (index: number, next: Partial<ReviewRoleInput>) => {
    onChange(roles.map((r, i) => (i === index ? { ...r, ...next } : r)));
  };
  const remove = (index: number) => {
    onChange(roles.filter((_, i) => i !== index).map((r, i) => ({ ...r, sortOrder: i })));
  };
  const add = () => onChange([...roles, newRole(roles.length)]);

  return (
    <div className="flex flex-col gap-4 py-2">
      {roles.length === 0 && (
        <p className="text-muted-foreground text-sm">No roles yet.</p>
      )}
      {roles.map((role, index) => (
        <RoleCard
          key={role.key}
          role={role}
          editing={editing}
          emsActive={emsActive}
          facts={facts}
          actorOptions={actorOptions}
          onChange={(next) => update(index, next)}
          onRemove={() => remove(index)}
        />
      ))}
      {editing && (
        <div>
          <Button type="button" variant="outline" size="sm" onClick={add}>
            <Plus /> Add role
          </Button>
        </div>
      )}
    </div>
  );
}

interface RoleCardProps {
  role: ReviewRoleInput;
  editing: boolean;
  emsActive: boolean;
  facts: RuleFact[];
  actorOptions: ReviewActorOptions;
  onChange: (next: Partial<ReviewRoleInput>) => void;
  onRemove: () => void;
}

/** A role's source is "configured" once its required binding/pool is present.
 * RULE has no hard requirement (an empty rule = no candidates yet), so only
 * EXPLICIT/PERSONA/STAFF_ROLE can be unconfigured. */
function isUnconfigured(role: ReviewRoleInput): boolean {
  if (role.actorSource === 'PERSONA') return !role.boundPersonaId;
  if (role.actorSource === 'STAFF_ROLE') return !role.boundStaffRoleId;
  if (role.actorSource === 'EXPLICIT') return (role.actors ?? []).length === 0;
  return false;
}

/** Plain, source-specific guidance for an unconfigured role (foolproof-UI —
 * no jargon like "source target"). */
function unconfiguredMessage(role: ReviewRoleInput): string {
  if (role.actorSource === 'PERSONA') return 'Choose a persona for this role.';
  if (role.actorSource === 'STAFF_ROLE') return 'Choose a staff role for this role.';
  // EXPLICIT
  const who = role.actorIdentityKind === 'user' ? 'staff member' : 'profile';
  return `Select at least one ${who} for this role.`;
}

function RoleCard({
  role,
  editing,
  emsActive,
  facts,
  actorOptions,
  onChange,
  onRemove,
}: RoleCardProps) {
  const { label } = useTerminology();
  const unconfigured = isUnconfigured(role);

  // The candidate pool for EXPLICIT / RULE follows the role's identity kind.
  const pool =
    role.actorIdentityKind === 'user' ? actorOptions.users : actorOptions.profiles;
  const selectedActorIds = (role.actors ?? []).map((a) => a.actorId);

  const setActorIds = (ids: string[]) => {
    onChange({
      actors: ids.map((id, i) => ({
        actorKind: role.actorIdentityKind,
        actorId: id,
        sortOrder: i,
        conditionsJson: null,
      })),
    });
  };

  // Switching identity kind clears the now-mismatched pool/bindings.
  const setIdentityKind = (kind: ReviewActorIdentityKind) => {
    onChange({
      actorIdentityKind: kind,
      actors: [],
      boundPersonaId: kind === 'profile' ? role.boundPersonaId : null,
    });
  };

  const setSource = (source: ReviewActorSource) => {
    onChange({
      actorSource: source,
      // Reset the previous source's sub-editor state to avoid stale config.
      actors: source === 'EXPLICIT' || source === 'RULE' ? (role.actors ?? []) : [],
      boundPersonaId: source === 'PERSONA' ? role.boundPersonaId : null,
      boundStaffRoleId: source === 'STAFF_ROLE' ? role.boundStaffRoleId : null,
      conditionsJson: source === 'RULE' ? role.conditionsJson : null,
      // STAFF_ROLE is inherently user-kind; PERSONA is profile-kind.
      actorIdentityKind:
        source === 'STAFF_ROLE'
          ? 'user'
          : source === 'PERSONA'
            ? 'profile'
            : role.actorIdentityKind,
    });
  };

  return (
    <div className="rounded-lg border border-border p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1 space-y-1.5">
          <Label>Label</Label>
          {editing ? (
            <Input
              aria-label="Role label"
              value={role.label}
              placeholder="e.g. Author, Reviewer, Chair"
              onChange={(e) => onChange({ label: e.target.value })}
              className="max-w-xs"
            />
          ) : (
            <p className="text-sm font-medium">{role.label || '—'}</p>
          )}
        </div>
        {editing && (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            mode="icon"
            aria-label="Remove role"
            onClick={onRemove}
          >
            <Trash2 className="size-4 text-muted-foreground" />
          </Button>
        )}
      </div>

      {/* Capabilities — these DRIVE behavior; the label is display-only. */}
      <div className="mt-4 space-y-1.5">
        <Label>Capabilities</Label>
        <div className="flex flex-wrap gap-4">
          <Capability
            label={`Can submit ${label('form').toLowerCase()}`}
            checked={role.canSubmit}
            disabled={!editing}
            onChange={(v) => onChange({ canSubmit: v })}
          />
          <Capability
            label="Can review"
            checked={role.canReview}
            disabled={!editing}
            onChange={(v) => onChange({ canReview: v })}
          />
          <Capability
            label="Can decide"
            checked={role.canDecide}
            disabled={!editing}
            onChange={(v) => onChange({ canDecide: v })}
          />
        </div>
      </div>

      {/* Identity kind + source */}
      <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div className="space-y-1.5">
          <Label>Identity</Label>
          {editing && role.actorSource !== 'PERSONA' && role.actorSource !== 'STAFF_ROLE' ? (
            <SearchSelect
              ariaLabel="Identity kind"
              value={role.actorIdentityKind}
              onChange={(v) => setIdentityKind(v as ReviewActorIdentityKind)}
              options={
                emsActive
                  ? [
                      { value: 'profile', label: IDENTITY_KIND_LABELS.profile },
                      { value: 'user', label: IDENTITY_KIND_LABELS.user },
                    ]
                  : [{ value: 'user', label: IDENTITY_KIND_LABELS.user }]
              }
            />
          ) : (
            <p className="text-muted-foreground text-sm">
              {IDENTITY_KIND_LABELS[role.actorIdentityKind]}
            </p>
          )}
        </div>
        <div className="space-y-1.5">
          <Label>Source</Label>
          {editing ? (
            <SearchSelect
              ariaLabel="Actor source"
              value={role.actorSource}
              onChange={(v) => setSource(v as ReviewActorSource)}
              options={sourceOptions(emsActive)}
            />
          ) : (
            <p className="text-muted-foreground text-sm">
              {sourceOptions(true).find((o) => o.value === role.actorSource)?.label ??
                role.actorSource}
            </p>
          )}
        </div>
      </div>

      {/* Source-specific sub-editor */}
      <div className="mt-4">
        {role.actorSource === 'EXPLICIT' && (
          <ActorPool
            label={`${role.actorIdentityKind === 'user' ? 'Staff users' : 'Profiles'}`}
            options={pool}
            value={selectedActorIds}
            disabled={!editing}
            onChange={setActorIds}
          />
        )}
        {role.actorSource === 'RULE' && (
          <div className="space-y-3">
            <div className="space-y-1.5">
              <Label>Match rule</Label>
              <RuleBuilder
                key={role.key}
                facts={facts}
                value={(role.conditionsJson as RuleGroup | null) ?? null}
                onChange={(g) => onChange({ conditionsJson: g })}
                disabled={!editing}
              />
            </div>
            <ActorPool
              label={`Candidate ${role.actorIdentityKind === 'user' ? 'staff users' : 'profiles'}`}
              options={pool}
              value={selectedActorIds}
              disabled={!editing}
              onChange={setActorIds}
            />
          </div>
        )}
        {role.actorSource === 'PERSONA' && (
          <div className="space-y-1.5">
            <Label>Persona</Label>
            <SearchSelect
              ariaLabel="Bound persona"
              value={role.boundPersonaId ?? null}
              onChange={(v) => onChange({ boundPersonaId: v })}
              options={actorOptions.personas}
              placeholder="Pick a persona…"
              disabled={!editing}
            />
          </div>
        )}
        {role.actorSource === 'STAFF_ROLE' && (
          <div className="space-y-1.5">
            <Label>Staff role</Label>
            <SearchSelect
              ariaLabel="Bound staff role"
              value={role.boundStaffRoleId ?? null}
              onChange={(v) => onChange({ boundStaffRoleId: v })}
              options={actorOptions.staffRoles}
              placeholder="Pick a staff role…"
              disabled={!editing}
            />
          </div>
        )}
      </div>

      {unconfigured && (
        <div
          role="alert"
          className="mt-4 flex items-start gap-2 rounded-md border border-[var(--color-warning-soft,var(--color-yellow-200))] bg-[var(--color-warning-soft,var(--color-yellow-50))] p-2.5 text-xs text-[var(--color-warning-accent,var(--color-yellow-700))]"
        >
          <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
          <span>{unconfiguredMessage(role)}</span>
        </div>
      )}
    </div>
  );
}

function Capability({
  label,
  checked,
  disabled,
  onChange,
}: {
  label: string;
  checked: boolean;
  disabled: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex items-center gap-2 text-sm">
      <Checkbox
        checked={checked}
        disabled={disabled}
        onCheckedChange={(v) => onChange(v === true)}
      />
      {label}
    </label>
  );
}

function ActorPool({
  label,
  options,
  value,
  disabled,
  onChange,
}: {
  label: string;
  options: SearchSelectOption[];
  value: string[];
  disabled: boolean;
  onChange: (ids: string[]) => void;
}) {
  return (
    <div className="space-y-1.5">
      <Label>{label}</Label>
      {disabled ? (
        <div className="flex flex-wrap gap-1.5">
          {value.length === 0 ? (
            <span className="text-muted-foreground text-sm">—</span>
          ) : (
            value.map((id) => (
              <Badge key={id} variant="secondary" appearance="light" size="sm">
                {options.find((o) => o.value === id)?.label ?? id}
              </Badge>
            ))
          )}
        </div>
      ) : (
        <MultiSelect
          options={options}
          value={value}
          onChange={onChange}
          placeholder="Select…"
        />
      )}
    </div>
  );
}
