'use client';

/**
 * The role Permissions tab under the Foundryx UIUX switch: one card per
 * module, one row per resource with a tick box per action and an All tick
 * (mixed while only some are on). Read mode shows the granted actions as
 * chips. The ticks write through `permission-ticks.ts`, which mirrors today's
 * dropdown, so the same ticks send the same grant set in both looks.
 */
import { useMemo } from 'react';
import type { UseFormReturn } from 'react-hook-form';
import { Checkbox } from '@/components/ui/checkbox';
import { FormField, FormItem } from '@/components/ui/form';
import { FxTooltip } from '@/components/fx/fx-tooltip';
import { keysForResource } from '@/lib/permissions';
import type { PermissionCatalog, PermissionResource } from '@/types/permission';
import { groupPermissionsByModule } from './group-permissions';
import {
  allResourceActionsOn,
  isImpliedRead,
  toggleAllResourceActions,
  toggleResourceAction,
} from './permission-ticks';
import type { RoleFormValues } from './role-schema';

const TICK_LABEL = 'flex items-center gap-2 text-sm text-(--fx-ink) select-none';

interface FxPermissionRowProps {
  resource: PermissionResource;
  editing: boolean;
  value: string[];
  onChange: (next: string[]) => void;
}

function FxPermissionRow({ resource, editing, value, onChange }: FxPermissionRowProps) {
  const selected = keysForResource(value, resource.resource);
  const granted = resource.actions.filter((a) => selected.includes(a.key));
  const allOn = allResourceActionsOn(value, resource);

  return (
    <div
      role="group"
      aria-label={resource.resourceLabel}
      data-fx-permission-row={resource.resource}
      className="grid grid-cols-1 gap-2 border-b border-(--fx-line) px-4 py-3 last:border-0 sm:grid-cols-[200px_1fr] sm:items-center sm:gap-4"
    >
      <span className="text-sm font-medium text-(--fx-ink)">{resource.resourceLabel}</span>
      {editing ? (
        <div className="flex flex-wrap items-center gap-x-5 gap-y-2.5">
          {resource.actions.length > 1 && (
            <label className={`${TICK_LABEL} font-medium`}>
              <Checkbox
                size="sm"
                checked={allOn ? true : selected.length > 0 ? 'indeterminate' : false}
                onCheckedChange={() => onChange(toggleAllResourceActions(value, resource))}
              />
              All
            </label>
          )}
          {resource.actions.map((action) => {
            const on = selected.includes(action.key);
            const implied = on && isImpliedRead(value, resource, action.key);
            const tick = (
              <label key={action.key} className={TICK_LABEL} data-fx-implied={implied ? '' : undefined}>
                <Checkbox
                  size="sm"
                  checked={on}
                  disabled={implied}
                  onCheckedChange={() => onChange(toggleResourceAction(value, resource, action.key))}
                />
                {action.actionLabel}
              </label>
            );
            return implied ? (
              <FxTooltip key={action.key} label="On with the other actions">
                {tick}
              </FxTooltip>
            ) : (
              tick
            );
          })}
        </div>
      ) : granted.length ? (
        <div className="flex flex-wrap items-center gap-1.5">
          {granted.map((action) => (
            <span
              key={action.key}
              className="rounded-(--fx-r-s) bg-(--fx-chip) px-2 py-0.5 text-xs font-medium text-(--fx-chip-ink)"
            >
              {action.actionLabel}
            </span>
          ))}
        </div>
      ) : (
        <span className="text-sm text-(--fx-ink-3)">No access</span>
      )}
    </div>
  );
}

export interface FxPermissionsTabProps {
  form: UseFormReturn<RoleFormValues>;
  editing: boolean;
  catalog: PermissionCatalog;
}

export function FxPermissionsTab({ form, editing, catalog }: FxPermissionsTabProps) {
  const groups = useMemo(() => groupPermissionsByModule(catalog), [catalog]);

  return (
    <FormField
      control={form.control}
      name="permissionKeys"
      render={({ field }) => (
        <FormItem>
          <div className="flex flex-col gap-4">
            {groups.map((group) => {
              const total = group.resources.reduce((n, r) => n + r.actions.length, 0);
              const on = group.resources.reduce(
                (n, r) => n + r.actions.filter((a) => field.value.includes(a.key)).length,
                0,
              );
              return (
                <section
                  key={group.module}
                  aria-label={group.label}
                  className="overflow-hidden rounded-(--fx-r-l) border border-(--fx-line) bg-(--fx-surface)"
                >
                  <div className="flex items-baseline justify-between gap-3 border-b border-(--fx-line) bg-(--fx-surface-2) px-4 py-2.5">
                    <h3 className="text-sm font-semibold text-(--fx-ink)">{group.label}</h3>
                    <span className="text-xs tabular-nums text-(--fx-ink-3)">
                      {on} of {total}
                    </span>
                  </div>
                  {group.resources.map((resource) => (
                    <FxPermissionRow
                      key={resource.resource}
                      resource={resource}
                      editing={editing}
                      value={field.value}
                      onChange={field.onChange}
                    />
                  ))}
                </section>
              );
            })}
          </div>
        </FormItem>
      )}
    />
  );
}
