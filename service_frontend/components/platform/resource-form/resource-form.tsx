'use client';

import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { ArrowLeft, ChevronLeft, ChevronRight, Pencil } from 'lucide-react';
import { toast } from 'sonner';
import { MENU_SIDEBAR } from '@/config/menu.config';
import { buildListNav } from '@/lib/list-context';
import { deferredDoneMessage, presentContinuous } from '@/lib/deferred-verb';
import { trackPendingEntities, untrackPendingEntities } from '@/lib/pending-entity-store';
import { useCan } from '@/hooks/use-can';
import { useDeferredAction } from '@/hooks/use-deferred-action';
import { useMenu } from '@/hooks/use-menu';
import { useTerminology } from '@/hooks/use-terminology';
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
import { Button } from '@/components/ui/button';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { PageHeader } from '@/components/platform/page-header';
import { ActionMenu } from '@/components/platform/resource-actions/action-menu';
import { DeferredCountdown } from '@/components/platform/resource-actions/deferred-action-button';
import { RecordNav } from './record-nav';
import type { ResourceFormConfig } from './types';

export interface ResourceFormProps<T> {
  config: ResourceFormConfig<T>;
}

/**
 * Naive English singularization for the sidebar's OWN label ("Users" ->
 * "user", "Templates" -> "template", "Statuses" -> "status") - good enough
 * for this app's regular-plural menu labels; entities with a terminology
 * `termKey` use the engine's real singular instead (see below) and never hit
 * this path.
 */
function singularize(plural: string): string {
  if (/ies$/i.test(plural)) return plural.replace(/ies$/i, 'y');
  if (/(s|x|z|ch|sh)es$/i.test(plural)) return plural.replace(/es$/i, '');
  if (/s$/i.test(plural) && !/ss$/i.test(plural)) return plural.replace(/s$/i, '');
  return plural;
}

/**
 * The system-wide form view (plan 02 §3b, restyled per plan 23 D5/D6): a
 * `PageHeader` toolbar row (crumbs + title left, ONE Back right, carrying
 * `ctx`/`i`/`from`) and, below it, the record card - identity (avatar, title,
 * subtitle) left and `RecordActions` right: record pager, a gear "…" menu
 * (secondary actions, a separator, then destructive last), then the primary
 * (Edit, or Cancel + Save while editing). Icon tabs and a global read/edit
 * toggle with a single save + unsaved-changes guard follow.
 */
export function ResourceForm<T>({ config }: ResourceFormProps<T>) {
  const [editing, setEditing] = useState(config.initialEditing ?? false);
  const [activeTab, setActiveTab] = useState(
    config.initialTabId ?? config.tabs[0]?.id,
  );
  const [saving, setSaving] = useState(false);
  const { can } = useCan();
  const canEdit = !config.editPermission || can(config.editPermission);
  const pathname = usePathname() ?? '';
  const searchParams = useSearchParams();
  const router = useRouter();
  const { getCurrentItem } = useMenu(pathname);
  const { label } = useTerminology();

  // Verb + noun on the primary Save/Create button (AC-DLA-35: no bare
  // "Save"/"Submit"/"OK") - derived from the SAME sidebar entry PageHeader
  // resolves its own title from, never a per-entity prop to thread through
  // every `useXForm` hook. Skipped for `embedded` (form-in-form) instances,
  // whose page route belongs to the PARENT record, not this one - a wrong
  // noun is worse than none.
  const currentItem = config.embedded ? undefined : getCurrentItem(MENU_SIDEBAR);
  const derivedNoun = currentItem?.termKey
    ? label(currentItem.termKey).toLowerCase()
    : currentItem?.title
      ? singularize(currentItem.title).toLowerCase()
      : undefined;
  const entityNoun = config.entityNoun ?? derivedNoun;
  const saveLabel = entityNoun ? `Save ${entityNoun}` : 'Save';
  const createLabel = entityNoun ? `Create ${entityNoun}` : 'Create';

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

  // Back carries ctx/i/from (AC-DLA-28/30): `from` is the record currently
  // open, read off the URL's own last path segment - every form route is
  // `.../<id>` (the `paths.ts` convention every entity already follows), so
  // this restores the right row on Back for any entity with no per-entity
  // wiring.
  const recordId = pathname.split('/').filter(Boolean).pop();
  const iParam = searchParams.get('i');
  const backHref = config.embedded
    ? null
    : buildListNav(config.backHref, {
        ctx: searchParams.get('ctx'),
        i:
          iParam !== null && Number.isFinite(Number(iParam))
            ? Number(iParam)
            : null,
        from: recordId,
      });

  // Deferred (grace-window) form-surface action (sprint-4/23 T5, AC-DLA-44):
  // the gear's Delete/Archive/etc. no longer opens a confirm dialog - it
  // parks on the server and the countdown REPLACES the primary area below.
  // On commit the record is gone, so the page returns to the list (`ctx`/
  // `i`/`from` preserved via the SAME `backHref` the record's own Back link
  // already computes).
  const deferredEntityTypeRef = useRef('');
  const deferredLabelRef = useRef('');
  // The entity type any of this record's registered deferred actions target -
  // `watchFromMount`/`watch` below needs it to ask `current` about THIS
  // record without waiting for a local click (AC-DLA-46, second-tab parity).
  const watchEntityType = config.actions.find((a) => a.deferred)?.deferred?.entityType;
  const deferred = useDeferredAction({
    watchFromMount: Boolean(!config.embedded && recordId && watchEntityType),
    watch:
      !config.embedded && recordId && watchEntityType
        ? { entityType: watchEntityType, entityId: recordId }
        : undefined,
    onCommitted: () => {
      if (recordId) untrackPendingEntities([recordId]);
      toast.success(deferredDoneMessage(deferredLabelRef.current || 'Delete', deferredEntityTypeRef.current, 1));
      router.push(backHref ?? config.backHref);
    },
    onFailed: (error) => {
      if (recordId) untrackPendingEntities([recordId]);
      toast.error(error || 'The action failed.');
    },
    onCancelledElsewhere: () => {
      if (recordId) untrackPendingEntities([recordId]);
    },
    onCancelFailed: (error) => {
      toast.error(error || 'Could not cancel that action.');
    },
  });

  const deferredPending = deferred.state.status === 'pending' ? deferred.state : null;
  // A countdown picked up via `watch` (another tab / a re-mount) never ran
  // through `onDeferredStart` - derive its label from the matching action's
  // OWN registered key. Fix round 1 item 11: this used to MUTATE a ref
  // directly in the render body and read that same ref back for the JSX
  // below (worked, but a ref write during render is a footgun the moment
  // something reads it before the write - StrictMode double-invokes render
  // for exactly this class of bug). `useMemo` derives it PURELY, fresh every
  // render, so the label the countdown displays is never stale-by-one-frame.
  const derivedDeferred = useMemo(() => {
    if (!deferredPending) return null;
    const matched = config.actions.find((a) => a.deferred?.actionKey === deferredPending.actionKey);
    if (!matched) return null;
    const label =
      typeof matched.label === 'function' ? matched.label(config.actionRows) : matched.label;
    return { label, entityType: matched.deferred?.entityType ?? '' };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- config.actions/actionRows are stable per render pass; re-run only when the pending action itself changes
  }, [deferredPending?.actionKey]);

  // `onCommitted` fires AFTER `deferredPending` has already gone back to
  // null (the poll that discovers the commit settles straight to `done`),
  // so it needs the LAST known label/entityType - cached here (a ref write
  // in an effect, not render, is fine: nothing reads it during rendering).
  useLayoutEffect(() => {
    if (!derivedDeferred) return;
    deferredLabelRef.current = derivedDeferred.label;
    deferredEntityTypeRef.current = derivedDeferred.entityType;
  }, [derivedDeferred]);

  const gear =
    !editing && !deferredPending && config.actions.some((a) => a.surfaces.form) ? (
      <ActionMenu
        actions={config.actions}
        rows={config.actionRows}
        getEntityId={config.getEntityId}
        runtime={{
          reload: config.onReload ?? (() => {}),
          backHref: backHref ?? undefined,
        }}
        surface="form"
        trigger="gear"
        onDeferredStart={(action, entityIds) => {
          // The label/entityType for THIS action reach the countdown via
          // `derivedDeferred` above the moment `deferred.state` flips to
          // `pending` (it re-derives from `config.actions` + the resulting
          // `actionKey`) - no need to cache anything eagerly here.
          const entityType = action.deferred!.entityType;
          trackPendingEntities(entityIds);
          // Fix round 1 item 5: mirror `action-menu.tsx`'s own try/catch - an
          // unhandled park rejection here (a 409 "another action is already
          // counting down") previously vanished silently, leaving the record
          // dimmed with no countdown and no way to tell what happened.
          deferred
            .start(
              action.deferred!.actionKey,
              entityIds.map((id) => ({ entityType, entityId: id })),
              action.deferred!.payload?.(config.actionRows),
            )
            .catch((error: unknown) => {
              untrackPendingEntities(entityIds);
              toast.error(error instanceof Error ? error.message : 'Could not start that action.');
            });
        }}
      />
    ) : null;

  // The countdown REPLACES the primary area only (AC-DLA-44) - identity,
  // gear-less record card and tabs stay put; no dialog, no full-page swap.
  const primary = deferredPending ? (
    <DeferredCountdown
      verb={derivedDeferred ? presentContinuous(derivedDeferred.label) : 'Working'}
      commitAt={deferredPending.commitAt}
      windowSeconds={deferredPending.windowSeconds}
      onCancel={() => {
        // Fix round 1 item 9: `deferred.cancel()` now leaves `pending`
        // SYNCHRONOUSLY (before its own network round-trip) - this whole
        // countdown unmounts on the SAME render, so there is no window
        // where a stale/disabled Cancel could be double-pressed.
        void deferred.cancel();
        if (recordId) untrackPendingEntities([recordId]);
      }}
    />
  ) : editing ? (
    <>
      <Button
        variant="outline"
        size="sm"
        onClick={handleCancel}
        disabled={saving}
      >
        Cancel
      </Button>
      <Button
        variant="primary"
        size="sm"
        onClick={handleSave}
        disabled={saving}
      >
        {config.editable ? saveLabel : config.backLabel ? createLabel : saveLabel}
      </Button>
    </>
  ) : (
    config.editable &&
    canEdit && (
      <Button variant="primary" size="sm" onClick={() => setEditing(true)}>
        <Pencil />
        Edit
      </Button>
    )
  );

  return (
    <div className="flex flex-col gap-5">
      {/* Toolbar row = PageHeader (D6): crumbs + title left, ONE Back right. */}
      {!config.embedded && (
        <PageHeader
          // AC-DLA-30/D6 fix round 1: config.breadcrumb (the record-level
          // trail, e.g. "Users > Jane Doe") names the record itself when a
          // form supplies one - PageHeader's own menu-derived trail is only
          // the fallback for the (currently unused) forms that leave it []
          // (BreadcrumbStep and PageHeaderCrumb share the same shape).
          crumbs={config.breadcrumb.length ? config.breadcrumb : undefined}
          actions={
            <Button variant="outline" size="sm" asChild>
              <Link href={backHref ?? config.backHref}>
                <ArrowLeft />
                {config.backLabel ?? 'Back'}
              </Link>
            </Button>
          }
        />
      )}

      {/* Record card top: identity left, RecordActions right (D5). Wraps
          under the identity at 375. */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 items-center gap-3">
          {config.avatar}
          <div className="flex min-w-0 flex-col">
            {/* Heading level 2 (AC-DLA-27) - `PageHeader` above owns the
                page's one top-level heading; this is the record's identity,
                not the page title. */}
            <h2 className="truncate text-xl font-semibold font-heading leading-tight">
              {config.title}
            </h2>
            {config.subtitle && (
              <span className="text-sm text-muted-foreground">
                {config.subtitle}
              </span>
            )}
          </div>
        </div>

        <div
          className="flex flex-wrap items-center gap-2"
          data-slot="record-actions"
        >
          {config.embedded && (
            <Button variant="outline" size="sm" onClick={config.onBack}>
              <ArrowLeft />
              {config.backLabel ?? 'Back'}
            </Button>
          )}

          {config.inlineNav && config.inlineNav.total > 1 && !editing && (
            <div className="flex items-center gap-1">
              <Button
                variant="outline"
                size="icon"
                className="size-7"
                onClick={config.inlineNav.onPrev}
                aria-label="Previous"
              >
                <ChevronLeft className="size-4" />
              </Button>
              <span className="px-1 text-xs tabular-nums text-muted-foreground">
                {config.inlineNav.index + 1} / {config.inlineNav.total}
              </span>
              <Button
                variant="outline"
                size="icon"
                className="size-7"
                onClick={config.inlineNav.onNext}
                aria-label="Next"
              >
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

          {gear}
          {primary}
        </div>
      </div>

      {/* Tabs - the strip scrolls horizontally on narrow screens (responsive
          mandate: five icon tabs exceed 375px; clipping would hide tabs). */}
      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList
          variant="line"
          className="w-full min-w-0 max-w-full overflow-x-auto"
        >
          {config.tabs.map((tab) => {
            const Icon = tab.icon;
            return (
              <TabsTrigger key={tab.id} value={tab.id} disabled={tab.disabled}>
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
