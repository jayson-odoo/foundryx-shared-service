'use client';

/**
 * Transition (edge) drawer (sprint-2/01) — label (the action button text),
 * fire-authorization roles (D5, MultiSelect) and the notify-on-transition
 * sub-form (D6: channel, recipients USER/ROLE/DYNAMIC, inline merge-field
 * template). Saving syncs the whole edge in one PATCH.
 */
import { useEffect, useState } from 'react';
import { useSession } from 'next-auth/react';
import { Eye, Plus, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Separator } from '@/components/ui/separator';
import { TemplateContentEditor } from '@/components/platform/template-preview/template-content-editor';
import type { TemplateDocument } from '@/types/templates';
import {
  Sheet,
  SheetBody,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet';
import { MergeFieldEditor, type MergeField } from '@/components/platform/merge-field-editor';
import { MultiSelect, type MultiSelectOption } from '@/components/platform/multi-select';
import { RuleBuilder } from '@/components/platform/rule-builder';
import { SearchSelect } from '@/components/platform/search-select';
import type { RuleFact, RuleGroup } from '@/types/rules';
import type {
  DynamicRecipientKey,
  NotificationRecipient,
  StatusNodeData,
  StatusTransition,
  TransitionNotification,
  TriggerMode,
} from '@/types/status-engine';

const DYNAMIC_OPTIONS: { value: DynamicRecipientKey; label: string }[] = [
  { value: 'ACTOR', label: 'Acting user' },
  { value: 'ASSIGNEE', label: 'Assignee' },
  { value: 'RECORD_OWNER', label: 'Record owner' },
];

/** Variables a notification template can use — chips insert them at the caret. */
const MERGE_FIELDS: MergeField[] = [
  { key: 'recordLabel', label: 'Record name' },
  { key: 'fromStatus', label: 'From status' },
  { key: 'toStatus', label: 'To status' },
  { key: 'transitionLabel', label: 'Action label' },
  { key: 'actorName', label: 'Acting user' },
  { key: 'entityLabel', label: 'Entity' },
];

export interface PendingEdge {
  fromStatusId: string;
  toStatusId: string;
}

export interface TransitionDrawerProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Existing edge to edit — or null with `pending` set for create-by-drag. */
  transition: StatusTransition | null;
  pending: PendingEdge | null;
  statuses: StatusNodeData[];
  /** Display label of the entity (template preview context). */
  entityLabel?: string;
  roleOptions: MultiSelectOption[];
  userOptions: MultiSelectOption[];
  /** Engine templates of the status.notification context (BL-081 picker). */
  templateOptions: MultiSelectOption[];
  /** Load a template's subject + flattened body + block doc (per-use copy). */
  onLoadTemplate?: (
    id: string,
  ) => Promise<{ subject: string; body: string; doc: TemplateDocument } | null>;
  /** Whitelisted rule facts for this entity (actor + record sources). */
  facts: RuleFact[];
  canManage: boolean;
  onCreate: (
    edge: PendingEdge,
    label: string,
    roleIds: string[],
    notifications: TransitionNotification[],
    conditions: RuleGroup | null,
    triggerMode: TriggerMode,
  ) => Promise<boolean>;
  onUpdate: (
    id: string,
    label: string,
    roleIds: string[],
    notifications: TransitionNotification[],
    conditions: RuleGroup | null,
    triggerMode: TriggerMode,
  ) => Promise<boolean>;
  onDelete: (id: string) => Promise<boolean>;
}

/** Picker sentinel — "no linked template, write a custom inline email". */
const CUSTOM_EMAIL = '';

function emptyNotification(): TransitionNotification {
  return {
    channel: 'EMAIL',
    templateSubject: '',
    templateBody: '',
    recipients: [{ targetType: 'DYNAMIC', dynamicKey: 'ACTOR' }],
  };
}

export function TransitionDrawer({
  open,
  onOpenChange,
  transition,
  pending,
  statuses,
  entityLabel,
  roleOptions,
  userOptions,
  templateOptions,
  onLoadTemplate,
  facts,
  canManage,
  onCreate,
  onUpdate,
  onDelete,
}: TransitionDrawerProps) {
  const { data: session } = useSession();
  const [label, setLabel] = useState('');
  const [roleIds, setRoleIds] = useState<string[]>([]);
  const [notifications, setNotifications] = useState<TransitionNotification[]>([]);
  const [conditions, setConditions] = useState<RuleGroup | null>(null);
  const [triggerMode, setTriggerMode] = useState<TriggerMode>('manual');
  // RuleBuilder is mount-initialized — bump to remount it with a fresh tree.
  const [builderEpoch, setBuilderEpoch] = useState(0);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Which notification's content editor dialog is open (null = none).
  const [editorIndex, setEditorIndex] = useState<number | null>(null);

  useEffect(() => {
    if (!open) return;
    setLabel(transition?.label ?? '');
    setRoleIds(transition?.roles.map((r) => r.id) ?? []);
    setNotifications(transition?.notifications.map((n) => ({ ...n })) ?? []);
    setConditions(transition?.conditionsJson ?? null);
    setTriggerMode(transition?.triggerMode ?? 'manual');
    setBuilderEpoch((epoch) => epoch + 1);
    setError(null);
  }, [open, transition]);

  const byId = new Map(statuses.map((s) => [s.id, s]));
  const fromId = transition?.fromStatusId ?? pending?.fromStatusId;
  const toId = transition?.toStatusId ?? pending?.toStatusId;
  const fromLabel = (fromId && byId.get(fromId)?.label) || '?';
  const toLabel = (toId && byId.get(toId)?.label) || '?';

  const patchNotification = (index: number, patch: Partial<TransitionNotification>) =>
    setNotifications((prev) => prev.map((n, i) => (i === index ? { ...n, ...patch } : n)));

  const patchRecipient = (
    notificationIndex: number,
    recipientIndex: number,
    patch: Partial<NotificationRecipient>,
  ) =>
    setNotifications((prev) =>
      prev.map((n, i) =>
        i === notificationIndex
          ? {
              ...n,
              recipients: n.recipients.map((r, j) =>
                j === recipientIndex ? { ...r, ...patch } : r,
              ),
            }
          : n,
      ),
    );

  const isAuto = triggerMode === 'auto';
  const hasConditions = Boolean(conditions && conditions.rules.length > 0);

  const validate = (): string | null => {
    if (!label.trim()) return 'Label is required.';
    // Auto edges are system-fired: they MUST carry conditions (an unconditioned
    // auto edge would fire always) — mirrors the backend 422 (sprint-4/03 G6).
    if (isAuto && !hasConditions)
      return 'An automatic transition needs at least one condition.';
    for (const notification of notifications) {
      if (!notification.templateSubject.trim() || !notification.templateBody.trim())
        return 'Notification subject and body are required.';
      if (notification.recipients.length === 0)
        return 'A notification needs at least one recipient.';
      for (const recipient of notification.recipients) {
        if (recipient.targetType !== 'DYNAMIC' && !recipient.targetId)
          return 'Pick a recipient for every notification entry.';
      }
    }
    return null;
  };

  const save = async () => {
    const problem = validate();
    if (problem) {
      setError(problem);
      return;
    }
    setError(null);
    setSaving(true);
    // Auto edges carry no roles (system-fired) — send an empty set regardless.
    const effectiveRoles = isAuto ? [] : roleIds;
    const ok = transition
      ? await onUpdate(transition.id, label, effectiveRoles, notifications, conditions, triggerMode)
      : pending
        ? await onCreate(pending, label, effectiveRoles, notifications, conditions, triggerMode)
        : false;
    setSaving(false);
    if (ok) onOpenChange(false);
  };

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="flex flex-col sm:max-w-lg">
        <SheetHeader>
          <SheetTitle>
            Transition — {fromLabel} → {toLabel}
          </SheetTitle>
        </SheetHeader>
        {/* Scrollable body + pinned footer — template editors grow tall. */}
        <SheetBody className="flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto">
          <div className="flex flex-col gap-2">
            <Label htmlFor="transition-label">
              Action label <span className="text-destructive">*</span>
            </Label>
            <Input
              id="transition-label"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder='Button text — e.g. "Approve"'
              disabled={!canManage}
            />
            {error && <p className="text-xs text-destructive">{error}</p>}
          </div>

          {/* Trigger mode (sprint-4/03) — a manual action button vs an
              engine-fired derivation when its conditions become true. */}
          <div className="flex flex-col gap-2">
            <Label>Trigger</Label>
            <SearchSelect
              options={[
                { value: 'manual', label: 'Manual' },
                { value: 'auto', label: 'Automatic' },
              ]}
              value={triggerMode}
              onChange={(value) => setTriggerMode(value as TriggerMode)}
              searchPlaceholder="Search…"
              disabled={!canManage}
            />
          </div>

          {/* Roles gate WHO fires a manual edge — meaningless for an auto edge. */}
          {!isAuto && (
            <div className="flex flex-col gap-2">
              <Label>Who can perform it</Label>
              <MultiSelect
                options={roleOptions}
                value={roleIds}
                onChange={setRoleIds}
                placeholder="Any role (unrestricted)"
                searchPlaceholder="Search roles…"
                disabled={!canManage}
              />
              <p className="text-xs text-muted-foreground">
                Empty = anyone allowed to act on the record. Otherwise the actor must hold at
                least one of these roles.
              </p>
            </div>
          )}

          {/* Rule-engine edge conditions (sprint-2/02) — evaluated at fire AND
              when listing available transitions; failing edges are hidden. For
              auto edges they ARE the derivation rule (required). */}
          <div className="flex flex-col gap-2">
            <Label>
              Conditions {isAuto && <span className="text-destructive">*</span>}
            </Label>
            <RuleBuilder
              key={builderEpoch}
              facts={facts}
              value={conditions}
              onChange={setConditions}
              disabled={!canManage}
            />
            {!isAuto && (
              <p className="text-xs text-muted-foreground">
                The transition is offered only while every condition passes. Empty = always
                allowed.
              </p>
            )}
          </div>

          <Separator />
          <div className="flex items-center justify-between">
            <div className="text-sm font-medium text-foreground">Notifications</div>
            {canManage && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => setNotifications((prev) => [...prev, emptyNotification()])}
              >
                <Plus className="size-3.5" /> Add notification
              </Button>
            )}
          </div>
          {notifications.length === 0 && (
            <p className="text-xs text-muted-foreground">
              No notifications — add one to email people when this transition fires.
            </p>
          )}
          {notifications.map((notification, index) => (
            <div key={index} className="flex flex-col gap-3 rounded-lg border border-border p-3.5">
              <div className="flex items-center justify-between gap-2">
                <SearchSelect
                  className="w-40"
                  options={[
                    { value: 'EMAIL', label: 'Email' },
                    { value: 'IN_APP', label: 'In-app (soon)' },
                  ]}
                  value={notification.channel}
                  onChange={(channel) =>
                    patchNotification(index, {
                      channel: channel as TransitionNotification['channel'],
                    })
                  }
                  searchPlaceholder="Search channels…"
                  disabled={!canManage}
                />
                {canManage && (
                  <Button
                    variant="ghost"
                    size="sm"
                    mode="icon"
                    aria-label="Remove notification"
                    onClick={() =>
                      setNotifications((prev) => prev.filter((_, i) => i !== index))
                    }
                  >
                    <Trash2 className="size-4 text-destructive" />
                  </Button>
                )}
              </div>

              {notification.channel === 'EMAIL' && (
                <>
                  {templateOptions.length > 0 && (
                    <div className="flex flex-col gap-2">
                      <Label>Email content</Label>
                      <SearchSelect
                        options={[
                          { value: CUSTOM_EMAIL, label: 'Custom email' },
                          ...templateOptions.map((o) => ({ value: o.value, label: o.label })),
                        ]}
                        value={notification.templateId ?? CUSTOM_EMAIL}
                        onChange={(value) => {
                          if (value === CUSTOM_EMAIL) {
                            patchNotification(index, { templateId: null, doc: null });
                            return;
                          }
                          // Copy the template's block doc for per-use editing —
                          // branded, but the wording is editable here.
                          void onLoadTemplate?.(value).then((loaded) =>
                            patchNotification(index, {
                              templateId: value,
                              ...(loaded
                                ? {
                                    doc: loaded.doc,
                                    templateSubject: loaded.subject,
                                    templateBody: loaded.body,
                                  }
                                : {}),
                            }),
                          );
                        }}
                        placeholder="Custom email"
                        searchPlaceholder="Search templates…"
                        disabled={!canManage}
                      />
                    </div>
                  )}

                  {notification.doc ? (
                    <div className="flex flex-col gap-2 rounded-md border border-dashed border-input bg-muted/30 p-3">
                      <p className="text-xs text-muted-foreground">
                        Branded email — edit the wording, or change layout in Templates.
                      </p>
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        className="self-start"
                        onClick={() => setEditorIndex(index)}
                      >
                        <Eye className="size-3.5" /> Edit &amp; preview
                      </Button>
                    </div>
                  ) : (
                    <MergeFieldEditor
                      subject={notification.templateSubject}
                      body={notification.templateBody}
                      onSubjectChange={(templateSubject) =>
                        patchNotification(index, { templateSubject })
                      }
                      onBodyChange={(templateBody) => patchNotification(index, { templateBody })}
                      fields={MERGE_FIELDS}
                      previewContext={{
                        recordLabel: `Sample ${entityLabel ?? 'record'}`,
                        fromStatus: fromLabel,
                        toStatus: toLabel,
                        transitionLabel: label || 'Move',
                        actorName: session?.user?.name ?? 'You',
                        entityLabel: entityLabel ?? '',
                      }}
                      subjectPlaceholder="Subject — e.g. {{recordLabel}} moved to {{toStatus}}"
                      bodyPlaceholder="Body…"
                      dialogTitle="Notification email"
                      disabled={!canManage}
                    />
                  )}
                </>
              )}

              <div className="flex flex-col gap-2">
                <div className="flex items-center justify-between">
                  <Label>Recipients</Label>
                  {canManage && (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() =>
                        patchNotification(index, {
                          recipients: [
                            ...notification.recipients,
                            { targetType: 'DYNAMIC', dynamicKey: 'ACTOR' },
                          ],
                        })
                      }
                    >
                      <Plus className="size-3.5" /> Add
                    </Button>
                  )}
                </div>
                {notification.recipients.map((recipient, recipientIndex) => (
                  <div key={recipientIndex} className="flex items-center gap-2">
                    <SearchSelect
                      className="w-32"
                      options={[
                        { value: 'DYNAMIC', label: 'Dynamic' },
                        { value: 'ROLE', label: 'Role' },
                        { value: 'USER', label: 'User' },
                      ]}
                      value={recipient.targetType}
                      onChange={(targetType) =>
                        patchRecipient(index, recipientIndex, {
                          targetType: targetType as NotificationRecipient['targetType'],
                          targetId: null,
                          dynamicKey: targetType === 'DYNAMIC' ? 'ACTOR' : null,
                        })
                      }
                      searchPlaceholder="Search types…"
                      disabled={!canManage}
                    />
                    {recipient.targetType === 'DYNAMIC' ? (
                      <SearchSelect
                        className="grow"
                        options={DYNAMIC_OPTIONS.map((o) => ({
                          value: o.value,
                          label: o.label,
                        }))}
                        value={recipient.dynamicKey ?? 'ACTOR'}
                        onChange={(dynamicKey) =>
                          patchRecipient(index, recipientIndex, {
                            dynamicKey: dynamicKey as DynamicRecipientKey,
                          })
                        }
                        searchPlaceholder="Search recipients…"
                        disabled={!canManage}
                      />
                    ) : (
                      <SearchSelect
                        className="grow"
                        options={recipient.targetType === 'ROLE' ? roleOptions : userOptions}
                        value={recipient.targetId ?? null}
                        onChange={(targetId) =>
                          patchRecipient(index, recipientIndex, { targetId })
                        }
                        placeholder={
                          recipient.targetType === 'ROLE' ? 'Pick a role…' : 'Pick a user…'
                        }
                        searchPlaceholder={
                          recipient.targetType === 'ROLE' ? 'Search roles…' : 'Search users…'
                        }
                        disabled={!canManage}
                      />
                    )}
                    {canManage && (
                      <Button
                        variant="ghost"
                        size="sm"
                        mode="icon"
                        aria-label="Remove recipient"
                        onClick={() =>
                          patchNotification(index, {
                            recipients: notification.recipients.filter(
                              (_, j) => j !== recipientIndex,
                            ),
                          })
                        }
                      >
                        <Trash2 className="size-3.5 text-muted-foreground" />
                      </Button>
                    )}
                  </div>
                ))}
              </div>
            </div>
          ))}
        </SheetBody>

        {editorIndex !== null && notifications[editorIndex]?.doc && (
          <TemplateContentEditor
            open={editorIndex !== null}
            onOpenChange={(o) => !o && setEditorIndex(null)}
            doc={notifications[editorIndex]!.doc as TemplateDocument}
            subject={notifications[editorIndex]!.templateSubject}
            contextKey="status.notification"
            onDocChange={(doc) => patchNotification(editorIndex, { doc })}
            onSubjectChange={(templateSubject) => patchNotification(editorIndex, { templateSubject })}
            title="Notification email"
            disabled={!canManage}
          />
        )}
        {canManage && (
          <div className="flex items-center justify-between gap-2.5 border-t border-border p-4">
            <div>
              {transition && (
                <Button
                  variant="destructive"
                  onClick={() =>
                    void onDelete(transition.id).then((ok) => ok && onOpenChange(false))
                  }
                >
                  Delete transition
                </Button>
              )}
            </div>
            <Button onClick={() => void save()} disabled={saving}>
              {transition ? 'Save' : 'Create transition'}
            </Button>
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}
