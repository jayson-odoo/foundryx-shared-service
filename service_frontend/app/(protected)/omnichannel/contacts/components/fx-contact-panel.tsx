'use client';

/**
 * Foundryx UIUX switch only (slice W1-CONTACT): the contact record's Details
 * side, matching the approved mock. Three sections in one card, each editing
 * on its own as today (owner choice, Q-EDIT):
 *
 * - Details: read as plain values (Hold to Copy); the pencil icon "Edit
 *   details" turns them into fields with Cancel and Save details. Save sends
 *   the same PATCH as the switch-off panel (`contactDetailsPatch`) and says
 *   so in a done toast with Undo, which PATCHes the old values back.
 * - Lifecycle: the stage chip and "Move to" (only the moves the stage
 *   machine allows). Done toast without Undo: moving back is not
 *   guaranteed to be allowed.
 * - Tags: chips with a × and "Add tag" (only tags the contact lacks). Done
 *   toast with Undo through the same tag PATCH.
 *
 * People without `contacts.manage` see plain values only (answers.md:
 * view-only pages as plain text). Same hooks and services as the switch-off
 * `ContactPanel`, so the data and its rules cannot drift.
 */
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Loader2, X } from 'lucide-react';
import type {
  ContactField,
  ContactTag,
  ContactTagRef,
  ConversationThread,
  PatchContactInput,
  VisitorProfile,
} from '@/types/omnichannel';
import { ApiError } from '@/lib/api-client';
import { toast } from '@/lib/toast';
import { cn } from '@/lib/utils';
import { useCan } from '@/hooks/use-can';
import { useContactFields } from '@/hooks/use-contact-fields';
import { useContactTags } from '@/hooks/use-contact-tags';
import { useLifecycleMoves } from '@/hooks/use-lifecycle-moves';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { PRESSED_CLASS } from '@/components/ui/primitive-classes';
import { FxIconAction } from '@/components/fx/actions/icon-action';
import { FxHoldToCopy } from '@/components/fx/copy/hold-to-copy';
import { FxFieldMessage } from '@/components/fx/fields/fx-input';
import { SearchSelect } from '@/components/platform/search-select';
import {
  contactCustomValues,
  contactDetailsDoneWhat,
  contactDetailsPatch,
  contactDetailsUndoPatch,
  contactLifecycleDoneWhat,
  contactSystemValues,
  contactTagDoneWhat,
  nextTagIds,
  type ContactSystemValues,
  type CustomFieldValue,
} from './contact-record-fx';
import { useFxActorName } from './contacts-fx';
import { FX_UNDO_SECONDS } from './use-contacts-fx-done';

export interface FxContactPanelProps {
  thread: ConversationThread;
  onPatchContact: (patch: PatchContactInput) => Promise<ConversationThread>;
  onMoveLifecycle: (toStatusId: string) => Promise<ConversationThread>;
  /** Told when the Details section starts or stops editing (the record
   *  arrows hide meanwhile). */
  onEditingChange?: (editing: boolean) => void;
}

function describe(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback;
}

export function FxContactPanel({
  thread,
  onPatchContact,
  onMoveLifecycle,
  onEditingChange,
}: FxContactPanelProps) {
  const { fields } = useContactFields(thread.workspaceId);
  const { tags: workspaceTags } = useContactTags(thread.workspaceId);

  return (
    <div
      data-testid="fx-contact-panel"
      className="flex flex-col divide-y divide-(--fx-line) rounded-(--fx-r-l) border border-(--fx-line) bg-(--fx-surface) text-(--fx-ink)"
    >
      <FxDetailsSection
        thread={thread}
        fields={fields}
        onSave={onPatchContact}
        onEditingChange={onEditingChange}
      />
      <FxLifecycleSection thread={thread} onMove={onMoveLifecycle} />
      <FxTagsSection
        thread={thread}
        workspaceTags={workspaceTags}
        onPatch={onPatchContact}
      />
    </div>
  );
}

function Section({
  title,
  action,
  children,
}: {
  title: string;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="flex flex-col gap-3 p-4 sm:p-5">
      <div className="flex min-h-9 items-center justify-between gap-2">
        <h2 className="text-base font-semibold text-(--fx-ink)">{title}</h2>
        {action}
      </div>
      {children}
    </section>
  );
}

/** A label above a value or a field. The value side owns its own message. */
function Fact({
  label,
  labelId,
  htmlFor,
  children,
}: {
  label: string;
  labelId?: string;
  htmlFor?: string;
  children: ReactNode;
}) {
  return (
    <div className="flex min-w-0 flex-col gap-1">
      {htmlFor ? (
        <label
          htmlFor={htmlFor}
          className="text-xs font-medium text-(--fx-ink-3)"
        >
          {label}
        </label>
      ) : (
        <span id={labelId} className="text-xs font-medium text-(--fx-ink-3)">
          {label}
        </span>
      )}
      {children}
    </div>
  );
}

/** A read value: plain text, Hold to Copy when there is something to copy. */
function Value({
  value,
  labelledBy,
}: {
  value: string | null | undefined;
  labelledBy?: string;
}) {
  if (!value) {
    return (
      <p aria-labelledby={labelledBy} className="text-sm text-(--fx-ink-3)">
        -
      </p>
    );
  }
  return (
    <p
      aria-labelledby={labelledBy}
      className="min-w-0 text-sm break-words text-(--fx-ink)"
    >
      <FxHoldToCopy>{value}</FxHoldToCopy>
    </p>
  );
}

// ---------------------------------------------------------------------------
// Details
// ---------------------------------------------------------------------------

function FxDetailsSection({
  thread,
  fields,
  onSave,
  onEditingChange,
}: {
  thread: ConversationThread;
  fields: ContactField[];
  onSave: (patch: PatchContactInput) => Promise<ConversationThread>;
  onEditingChange?: (editing: boolean) => void;
}) {
  const visibleFields = useMemo(
    () =>
      fields
        .filter((f) => f.visibility === 'always')
        .sort((a, b) => a.sortOrder - b.sortOrder),
    [fields],
  );
  const { can } = useCan();
  const canManage = can('contacts.manage');
  const actor = useFxActorName();
  const [editing, setEditing] = useState(false);
  const [system, setSystem] = useState<ContactSystemValues>(() =>
    contactSystemValues(thread),
  );
  const [custom, setCustom] = useState<Record<string, CustomFieldValue>>(() =>
    contactCustomValues(thread, fields),
  );
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);

  // Same draft rules as the switch-off panel: Save diffs against the values
  // when editing started; while editing, a field the person has not touched
  // follows live updates (and its baseline with it), a touched one keeps
  // what was typed.
  const baselineRef = useRef({
    system: contactSystemValues(thread),
    custom: contactCustomValues(thread, fields),
  });
  const touchedSystemRef = useRef<Set<keyof ContactSystemValues>>(new Set());
  const touchedCustomRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    onEditingChange?.(editing);
  }, [editing, onEditingChange]);
  useEffect(() => () => onEditingChange?.(false), [onEditingChange]);

  useEffect(() => {
    const freshSystem = contactSystemValues(thread);
    const freshCustom = contactCustomValues(thread, fields);
    if (!editing) {
      setSystem(freshSystem);
      setCustom(freshCustom);
      baselineRef.current = { system: freshSystem, custom: freshCustom };
      touchedSystemRef.current = new Set();
      touchedCustomRef.current = new Set();
      return;
    }
    setSystem((prev) => {
      let changed = false;
      const next = { ...prev };
      (Object.keys(freshSystem) as (keyof ContactSystemValues)[]).forEach(
        (key) => {
          if (
            !touchedSystemRef.current.has(key) &&
            prev[key] !== freshSystem[key]
          ) {
            next[key] = freshSystem[key];
            changed = true;
          }
        },
      );
      return changed ? next : prev;
    });
    setCustom((prev) => {
      let changed = false;
      const next = { ...prev };
      for (const f of fields) {
        if (
          !touchedCustomRef.current.has(f.key) &&
          prev[f.key] !== freshCustom[f.key]
        ) {
          next[f.key] = freshCustom[f.key];
          changed = true;
        }
      }
      return changed ? next : prev;
    });
    const nextBaselineSystem = { ...baselineRef.current.system };
    (Object.keys(freshSystem) as (keyof ContactSystemValues)[]).forEach(
      (key) => {
        if (!touchedSystemRef.current.has(key))
          nextBaselineSystem[key] = freshSystem[key];
      },
    );
    const nextBaselineCustom = { ...baselineRef.current.custom };
    for (const f of fields) {
      if (!touchedCustomRef.current.has(f.key))
        nextBaselineCustom[f.key] = freshCustom[f.key];
    }
    baselineRef.current = {
      system: nextBaselineSystem,
      custom: nextBaselineCustom,
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- the same fields the switch-off panel watches
  }, [
    thread.id,
    thread.firstName,
    thread.lastName,
    thread.email,
    thread.language,
    thread.countryCode,
    thread.customFields,
    fields,
    editing,
  ]);

  const startEdit = () => {
    const freshSystem = contactSystemValues(thread);
    const freshCustom = contactCustomValues(thread, fields);
    setSystem(freshSystem);
    setCustom(freshCustom);
    baselineRef.current = { system: freshSystem, custom: freshCustom };
    touchedSystemRef.current = new Set();
    touchedCustomRef.current = new Set();
    setFieldErrors({});
    setEditing(true);
  };
  const cancel = () => {
    setSystem(contactSystemValues(thread));
    setCustom(contactCustomValues(thread, fields));
    setFieldErrors({});
    setEditing(false);
  };

  const save = async () => {
    setSaving(true);
    setFieldErrors({});
    try {
      const baseline = baselineRef.current;
      const patch = contactDetailsPatch(system, custom, baseline, fields);
      if (Object.keys(patch).length === 0) {
        setEditing(false);
        return;
      }
      await onSave(patch);
      setEditing(false);
      const undoPatch = contactDetailsUndoPatch(patch, baseline);
      const name = thread.name;
      toast.fxDone({
        what: contactDetailsDoneWhat(name),
        byWhom: actor,
        seconds: FX_UNDO_SECONDS,
        undo: () => {
          void onSave(undoPatch)
            .then(() =>
              toast.fxDone({
                what: `${name}'s details put back`,
                byWhom: actor,
              }),
            )
            .catch((error: unknown) =>
              toast.error(describe(error, 'Could not undo the change.')),
            );
        },
      });
    } catch (error) {
      if (error instanceof ApiError && error.status === 422) {
        const errs = (
          error.detail as { fieldErrors?: Record<string, string> } | undefined
        )?.fieldErrors;
        setFieldErrors(errs ?? { _: error.message });
      } else {
        setFieldErrors({
          _:
            error instanceof Error
              ? error.message
              : 'Could not save the contact.',
        });
      }
    } finally {
      setSaving(false);
    }
  };

  const touch = (key: keyof ContactSystemValues, value: string) => {
    touchedSystemRef.current.add(key);
    setSystem((s) => ({ ...s, [key]: value }));
  };

  const systemRow = (
    key: keyof ContactSystemValues,
    label: string,
    id: string,
    extra?: { placeholder?: string; type?: string; upper?: boolean },
  ) => (
    <Fact
      label={label}
      htmlFor={editing ? id : undefined}
      labelId={editing ? undefined : `${id}-label`}
    >
      {editing ? (
        <div className="relative">
          <Input
            id={id}
            type={extra?.type}
            placeholder={extra?.placeholder}
            maxLength={extra?.upper ? 2 : undefined}
            value={system[key]}
            onChange={(e) =>
              touch(
                key,
                extra?.upper ? e.target.value.toUpperCase() : e.target.value,
              )
            }
            className={cn(extra?.upper && 'uppercase')}
            aria-invalid={fieldErrors[key] ? true : undefined}
          />
          <FxFieldMessage>{fieldErrors[key]}</FxFieldMessage>
        </div>
      ) : (
        <Value value={thread[key]} labelledBy={`${id}-label`} />
      )}
    </Fact>
  );

  return (
    <Section
      title="Details"
      action={
        editing ? (
          <div className="flex items-center gap-1">
            <Button
              type="button"
              variant="fx-text"
              size="sm"
              onClick={cancel}
              disabled={saving}
            >
              Cancel
            </Button>
            <Button
              type="button"
              variant="fx-main"
              size="sm"
              onClick={() => void save()}
              disabled={saving}
              data-testid="contact-details-save"
              className="px-4"
            >
              {saving && <Loader2 className="size-3.5 animate-spin" />}
              Save details
            </Button>
          </div>
        ) : (
          canManage && (
            <FxIconAction
              mini
              label="Edit details"
              icon="edit"
              onClick={startEdit}
              data-testid="contact-details-edit"
            />
          )
        )
      }
    >
      {fieldErrors._ && (
        <p role="alert" className="text-xs text-(--fx-act)">
          {fieldErrors._}
        </p>
      )}
      <div className="grid grid-cols-1 gap-x-6 gap-y-5 sm:grid-cols-2">
        {systemRow('firstName', 'First name', 'fx-cd-first-name')}
        {systemRow('lastName', 'Last name', 'fx-cd-last-name')}
        {/* Phone is never editable here: it is the inbound stitch key and the
            PATCH refuses it (as with the switch off). */}
        <Fact label="Phone" labelId="fx-cd-phone-label">
          <Value value={thread.phone} labelledBy="fx-cd-phone-label" />
        </Fact>
        {systemRow('email', 'Email', 'fx-cd-email', { type: 'email' })}
        {systemRow('language', 'Language', 'fx-cd-language', {
          placeholder: 'en',
        })}
        {systemRow('countryCode', 'Country', 'fx-cd-country', {
          placeholder: 'MY',
          upper: true,
        })}
        {visibleFields.map((f) => (
          <Fact
            key={f.id}
            label={f.label}
            htmlFor={editing ? `fx-cd-cf-${f.id}` : undefined}
            labelId={editing ? undefined : `fx-cd-cf-${f.id}-label`}
          >
            <div className="relative">
              <FxCustomField
                field={f}
                editing={editing}
                value={custom[f.key] ?? null}
                onChange={(v) => {
                  touchedCustomRef.current.add(f.key);
                  setCustom((c) => ({ ...c, [f.key]: v }));
                }}
              />
              <FxFieldMessage>
                {fieldErrors[`customFields.${f.key}`]}
              </FxFieldMessage>
            </div>
          </Fact>
        ))}
      </div>
      <FxVisitorProvided profile={thread.visitorProfile} />
    </Section>
  );
}

function FxVisitorProvided({ profile }: { profile?: VisitorProfile | null }) {
  const rows = [
    { label: 'Name', value: profile?.name ?? '' },
    { label: 'Email', value: profile?.email ?? '' },
    { label: 'Phone', value: profile?.phone ?? '' },
  ].filter((r) => r.value.trim().length > 0);
  if (rows.length === 0) return null;
  return (
    <div className="flex flex-col gap-3 border-t border-(--fx-line) pt-4">
      <h3 className="text-sm font-semibold text-(--fx-ink-2)">
        Visitor provided
      </h3>
      <div className="grid grid-cols-1 gap-x-6 gap-y-4 sm:grid-cols-2">
        {rows.map((row) => (
          <Fact
            key={row.label}
            label={row.label}
            labelId={`fx-cd-vp-${row.label}`}
          >
            <Value value={row.value} labelledBy={`fx-cd-vp-${row.label}`} />
          </Fact>
        ))}
      </div>
    </div>
  );
}

function FxCustomField({
  field,
  editing,
  value,
  onChange,
}: {
  field: ContactField;
  editing: boolean;
  value: CustomFieldValue;
  onChange: (value: CustomFieldValue) => void;
}) {
  const id = `fx-cd-cf-${field.id}`;
  const labelledBy = `${id}-label`;
  if (!editing) {
    if (field.type === 'checkbox') {
      return (
        <p aria-labelledby={labelledBy} className="text-sm text-(--fx-ink)">
          {value ? 'Yes' : 'No'}
        </p>
      );
    }
    return (
      <Value
        value={
          value === null || value === undefined || value === ''
            ? null
            : String(value)
        }
        labelledBy={labelledBy}
      />
    );
  }
  switch (field.type) {
    case 'list':
      return (
        <SearchSelect
          options={(field.options ?? []).map((o) => ({ label: o, value: o }))}
          value={typeof value === 'string' ? value : null}
          onChange={(v) => onChange(v)}
          ariaLabel={field.label}
        />
      );
    case 'checkbox':
      return (
        <div className="flex h-9 items-center">
          <Checkbox
            id={id}
            checked={!!value}
            onCheckedChange={(v) => onChange(v === true)}
          />
        </div>
      );
    case 'number':
      return (
        <Input
          id={id}
          type="number"
          value={value === null || value === undefined ? '' : String(value)}
          onChange={(e) =>
            onChange(e.target.value === '' ? null : Number(e.target.value))
          }
        />
      );
    case 'date':
    case 'time':
    case 'url':
    case 'email':
      return (
        <Input
          id={id}
          type={field.type}
          value={typeof value === 'string' ? value : ''}
          onChange={(e) => onChange(e.target.value || null)}
        />
      );
    default:
      return (
        <Input
          id={id}
          value={typeof value === 'string' ? value : ''}
          onChange={(e) => onChange(e.target.value || null)}
        />
      );
  }
}

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

function FxStageChip({
  label,
  color,
}: {
  label: string;
  color: string | null;
}) {
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-(--fx-r-pill) bg-(--fx-chip) px-2.5 py-1 text-xs font-semibold text-(--fx-chip-ink)"
      data-testid="fx-lifecycle-stage"
    >
      <span
        aria-hidden="true"
        className="size-2 rounded-full bg-current"
        style={color ? { color } : undefined}
      />
      {label}
    </span>
  );
}

function FxLifecycleSection({
  thread,
  onMove,
}: {
  thread: ConversationThread;
  onMove: (toStatusId: string) => Promise<ConversationThread>;
}) {
  const lifecycle = thread.lifecycle;
  const { can } = useCan();
  const canManage = can('contacts.manage');
  const actor = useFxActorName();
  const changeSignal = [
    thread.priority,
    thread.assignedUserId,
    thread.cswExpiresAt,
    thread.lastMessageAt,
    thread.language,
    thread.countryCode,
    thread.email,
    thread.firstName,
    thread.lastName,
  ].join('|');
  const { moves, loading, refetch } = useLifecycleMoves(
    thread.id,
    lifecycle?.key,
    changeSignal,
  );
  const [moving, setMoving] = useState(false);

  const runMove = async (toStatusId: string) => {
    const stage = moves.find((m) => m.toStatusId === toStatusId)?.label ?? '';
    setMoving(true);
    try {
      const updated = await onMove(toStatusId);
      // No Undo: a move runs the stage machine, and moving back is not
      // guaranteed to be allowed or to undo what the move set off.
      toast.fxDone({
        what: contactLifecycleDoneWhat(
          thread.name,
          updated?.lifecycle?.label ?? stage,
        ),
        byWhom: actor,
      });
    } catch (error) {
      if (error instanceof ApiError) {
        const d = error.detail as { message?: string } | undefined;
        toast.error(d?.message ?? error.message);
        if (error.status === 409) refetch();
      } else {
        toast.error('Could not move this contact.');
      }
    } finally {
      setMoving(false);
    }
  };

  return (
    <Section title="Lifecycle">
      {!lifecycle ? (
        <p className="text-sm text-(--fx-ink-3)">Not available yet.</p>
      ) : (
        <div
          className="flex flex-wrap items-center gap-3"
          data-testid="lifecycle-section"
        >
          <FxStageChip label={lifecycle.label} color={lifecycle.color} />
          {moving && (
            <Loader2
              aria-hidden="true"
              className="size-3.5 animate-spin text-(--fx-ink-3)"
            />
          )}
          {canManage && !loading && moves.length > 0 && (
            <div className="w-full sm:w-56">
              <SearchSelect
                options={moves.map((m) => ({
                  label: m.label,
                  value: m.toStatusId,
                }))}
                value={null}
                onChange={(v) => void runMove(v)}
                placeholder="Move to…"
                ariaLabel="Move to"
                disabled={moving}
              />
            </div>
          )}
          {!loading && moves.length === 0 && (
            <p className="text-xs text-(--fx-ink-3)">
              No further moves from this stage.
            </p>
          )}
        </div>
      )}
    </Section>
  );
}

// ---------------------------------------------------------------------------
// Tags
// ---------------------------------------------------------------------------

function FxTagsSection({
  thread,
  workspaceTags,
  onPatch,
}: {
  thread: ConversationThread;
  workspaceTags: ContactTag[];
  onPatch: (patch: PatchContactInput) => Promise<ConversationThread>;
}) {
  const tags = thread.tags;
  const { can } = useCan();
  const canManage = can('contacts.manage');
  const actor = useFxActorName();
  const [optimistic, setOptimistic] = useState<ContactTagRef[] | null>(null);
  const [busy, setBusy] = useState(false);
  const shown = optimistic ?? tags;
  // The latest tags, for an Undo pressed after other changes landed.
  const latestRef = useRef(tags);
  useEffect(() => {
    latestRef.current = tags;
    setOptimistic(null);
  }, [tags]);

  const available = useMemo(
    () => workspaceTags.filter((wt) => !shown.some((t) => t.id === wt.id)),
    [workspaceTags, shown],
  );

  const apply = async (
    nextIds: string[],
    nextRefs: ContactTagRef[],
    done: { mode: 'add' | 'remove'; tag: ContactTagRef },
  ) => {
    setOptimistic(nextRefs);
    setBusy(true);
    try {
      await onPatch({ tagIds: nextIds });
      const name = thread.name;
      const reverse =
        done.mode === 'add' ? { remove: done.tag.id } : { add: done.tag.id };
      toast.fxDone({
        what: contactTagDoneWhat(name, done.mode, done.tag.name),
        byWhom: actor,
        seconds: FX_UNDO_SECONDS,
        undo: () => {
          void onPatch({ tagIds: nextTagIds(latestRef.current, reverse) })
            .then(() =>
              toast.fxDone({
                what: contactTagDoneWhat(
                  name,
                  done.mode === 'add' ? 'remove' : 'add',
                  done.tag.name,
                ),
                byWhom: actor,
              }),
            )
            .catch((error: unknown) =>
              toast.error(describe(error, 'Could not undo the change.')),
            );
        },
      });
    } catch (error) {
      setOptimistic(null);
      toast.error(describe(error, 'Could not update tags.'));
    } finally {
      setBusy(false);
    }
  };

  const addTag = (tagId: string) => {
    const tag = workspaceTags.find((t) => t.id === tagId);
    if (!tag) return;
    const ref: ContactTagRef = {
      id: tag.id,
      name: tag.name,
      emoji: tag.emoji,
      color: tag.color,
    };
    const nextRefs = [...shown, ref];
    void apply(
      nextRefs.map((t) => t.id),
      nextRefs,
      { mode: 'add', tag: ref },
    );
  };

  const removeTag = (tag: ContactTagRef) => {
    const nextRefs = shown.filter((t) => t.id !== tag.id);
    void apply(
      nextRefs.map((t) => t.id),
      nextRefs,
      { mode: 'remove', tag },
    );
  };

  return (
    <Section title="Tags">
      <div
        className="flex flex-wrap items-center gap-2"
        data-testid="tag-chips-section"
      >
        {shown.length === 0 && (
          <p className="text-sm text-(--fx-ink-3)">No tags yet.</p>
        )}
        {shown.map((tag) => (
          <span
            key={tag.id}
            className="group/chip relative inline-flex items-center gap-1 rounded-(--fx-r-pill) bg-(--fx-chip) py-1 ps-2.5 pe-1.5 text-xs font-semibold text-(--fx-chip-ink)"
          >
            {tag.color && (
              <span
                aria-hidden="true"
                className="size-2 rounded-full"
                style={{ backgroundColor: tag.color }}
              />
            )}
            {tag.emoji && <span aria-hidden="true">{tag.emoji}</span>}
            {tag.name}
            {canManage && (
              <button
                type="button"
                aria-label={`Remove ${tag.name}`}
                title="Remove"
                onClick={() => removeTag(tag)}
                disabled={busy}
                className={cn(
                  'inline-flex size-5 items-center justify-center rounded-full text-(--fx-ink-3) transition-[color,background-color] duration-(--fx-t-hover) ease-(--fx-ease-out) hover:bg-(--fx-act) hover:text-(--fx-act-ink) focus-visible:bg-(--fx-act) focus-visible:text-(--fx-act-ink) focus-visible:outline-none disabled:opacity-50',
                  PRESSED_CLASS,
                )}
              >
                <X aria-hidden="true" className="size-3" />
              </button>
            )}
          </span>
        ))}
        {canManage && available.length > 0 && (
          <div className="w-full sm:w-44">
            <SearchSelect
              options={available.map((t) => ({
                label: `${t.emoji ? `${t.emoji} ` : ''}${t.name}`,
                value: t.id,
              }))}
              value={null}
              onChange={addTag}
              placeholder="Add tag"
              ariaLabel="Add tag"
              disabled={busy}
            />
          </div>
        )}
      </div>
    </Section>
  );
}
