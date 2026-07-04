'use client';

import { Fragment, useEffect, useState } from 'react';
import Link from 'next/link';
import { ArrowLeft, ChevronLeft, ChevronRight, Pencil } from 'lucide-react';
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from '@/components/ui/breadcrumb';
import { Button } from '@/components/ui/button';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { ActionMenu } from '@/components/platform/resource-actions/action-menu';
import { useCan } from '@/hooks/use-can';
import { RecordNav } from './record-nav';
import type { ResourceFormConfig } from './types';

export interface ResourceFormProps<T> {
  config: ResourceFormConfig<T>;
}

/**
 * The system-wide form view (plan 02 §3b): breadcrumb, identifier header,
 * top-right record-nav + primary button + "…" actions, icon tabs, and a global
 * read/edit toggle with a single save + unsaved-changes guard.
 */
export function ResourceForm<T>({ config }: ResourceFormProps<T>) {
  const [editing, setEditing] = useState(config.initialEditing ?? false);
  const [activeTab, setActiveTab] = useState(config.initialTabId ?? config.tabs[0]?.id);
  const [saving, setSaving] = useState(false);
  const { can } = useCan();
  const canEdit = !config.editPermission || can(config.editPermission);

  // Warn on browser-level leave while there are unsaved edits.
  useEffect(() => {
    if (!editing || !config.isDirty) return;
    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = '';
    };
    window.addEventListener('beforeunload', handler);
    return () => window.removeEventListener('beforeunload', handler);
  }, [editing, config.isDirty]);

  // Dirty-guard via the Metronic AlertDialog (no ugly native window.confirm).
  // `guard(proceed)` runs `proceed` immediately when clean, else defers it
  // behind the Discard-changes dialog (RecordNav + Cancel both use it).
  const [pendingAction, setPendingAction] = useState<(() => void) | null>(null);
  const guard = (proceed: () => void) => {
    if (!config.isDirty) {
      proceed();
      return;
    }
    setPendingAction(() => proceed);
  };

  async function handleSave() {
    setSaving(true);
    try {
      const ok = await config.onSave();
      if (ok && config.editable) setEditing(false);
    } finally {
      setSaving(false);
    }
  }

  function handleCancel() {
    guard(() => {
      config.onCancel();
      if (config.editable) setEditing(false);
    });
  }

  return (
    <div className="flex flex-col gap-5">
      {/* Breadcrumb + top-right cluster */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        {config.embedded ? (
          <span />
        ) : (
          <Breadcrumb>
            <BreadcrumbList>
              {config.breadcrumb.map((step, i) => {
                const last = i === config.breadcrumb.length - 1;
                return (
                  <Fragment key={`${step.label}-${i}`}>
                    <BreadcrumbItem>
                      {last || !step.href ? (
                        <BreadcrumbPage>{step.label}</BreadcrumbPage>
                      ) : (
                        <BreadcrumbLink asChild>
                          <Link href={step.href}>{step.label}</Link>
                        </BreadcrumbLink>
                      )}
                    </BreadcrumbItem>
                    {!last && <BreadcrumbSeparator />}
                  </Fragment>
                );
              })}
            </BreadcrumbList>
          </Breadcrumb>
        )}

        <div className="flex items-center gap-2">
          {config.inlineNav && config.inlineNav.total > 1 && !editing && (
            <div className="flex items-center gap-1">
              <Button variant="outline" size="icon" className="size-7" onClick={config.inlineNav.onPrev} aria-label="Previous">
                <ChevronLeft className="size-4" />
              </Button>
              <span className="px-1 text-xs tabular-nums text-muted-foreground">
                {config.inlineNav.index + 1} / {config.inlineNav.total}
              </span>
              <Button variant="outline" size="icon" className="size-7" onClick={config.inlineNav.onNext} aria-label="Next">
                <ChevronRight className="size-4" />
              </Button>
            </div>
          )}
          {config.recordNav && !editing && (
            <RecordNav
              fetchAt={config.recordNav.fetchAt}
              buildHref={config.recordNav.buildHref}
              guard={guard}
            />
          )}

          {editing ? (
            <>
              <Button variant="outline" size="sm" onClick={handleCancel} disabled={saving}>
                Cancel
              </Button>
              <Button variant="primary" size="sm" onClick={handleSave} disabled={saving}>
                {config.editable ? 'Save' : (config.backLabel ? 'Create' : 'Save')}
              </Button>
            </>
          ) : (
            config.editable && canEdit && (
              <Button variant="primary" size="sm" onClick={() => setEditing(true)}>
                <Pencil />
                Edit
              </Button>
            )
          )}

          {!editing && config.actions.some((a) => a.surfaces.form) && (
            <ActionMenu
              actions={config.actions}
              rows={config.actionRows}
              runtime={{ reload: config.onReload ?? (() => {}) }}
              surface="form"
            />
          )}

          {config.embedded ? (
            <Button variant="outline" size="sm" onClick={config.onBack}>
              <ArrowLeft />
              {config.backLabel ?? 'Back'}
            </Button>
          ) : (
            <Button variant="outline" size="sm" asChild>
              <Link href={config.backHref}>
                <ArrowLeft />
                {config.backLabel ?? 'Back'}
              </Link>
            </Button>
          )}
        </div>
      </div>

      {/* Identifier header */}
      <div className="flex items-center gap-3">
        {config.avatar}
        <div className="flex flex-col">
          <h1 className="text-xl font-semibold font-heading leading-tight">{config.title}</h1>
          {config.subtitle && <span className="text-sm text-muted-foreground">{config.subtitle}</span>}
        </div>
      </div>

      {/* Tabs — the strip scrolls horizontally on narrow screens (responsive
          mandate: five icon tabs exceed 375px; clipping would hide tabs). */}
      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList variant="line" className="max-w-full overflow-x-auto">
          {config.tabs.map((tab) => {
            const Icon = tab.icon;
            return (
              <TabsTrigger key={tab.id} value={tab.id}>
                {Icon && <Icon />}
                {tab.label}
              </TabsTrigger>
            );
          })}
        </TabsList>
        {config.tabs.map((tab) => (
          <TabsContent key={tab.id} value={tab.id} className="pt-2">
            {tab.render({ editing })}
          </TabsContent>
        ))}
      </Tabs>

      <AlertDialog
        open={pendingAction !== null}
        onOpenChange={(open) => {
          if (!open) setPendingAction(null);
        }}
      >
        <AlertDialogContent className="md:max-w-[400px]">
          <AlertDialogHeader>
            <AlertDialogTitle>Discard changes?</AlertDialogTitle>
            <AlertDialogDescription>
              You have unsaved changes. If you continue, they will be lost.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Keep editing</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                pendingAction?.();
                setPendingAction(null);
              }}
            >
              Discard changes
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
