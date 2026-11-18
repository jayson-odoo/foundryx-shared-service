'use client';

import { useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useSession } from 'next-auth/react';
import {
  Archive,
  CirclePause,
  CirclePlay,
  ExternalLink,
  Pencil,
  Trash2,
} from 'lucide-react';
import { toast } from '@/lib/toast';
import { useFx } from '@/hooks/use-fx';
import type { FxIconRef } from '@/components/fx/icons';
import type {
  StatusGraph,
  StatusNodeData,
  StatusTransition,
} from '@/types/status-engine';
import type { TenantListItem } from '@/types/tenant-admin';
import { tenantUrl } from '@/lib/tenant';
import { tenantAdminService } from '@/services/tenant-admin-service';
import type { ResourceAction } from '@/components/platform/resource-list';
import { tenantFormHref } from './paths';

/**
 * The Tenant action registry (plan 07 §9, reworked sprint-2/01 / BL-059).
 * Lifecycle actions are GRAPH-DRIVEN: each outgoing edge of the tenant
 * status machine becomes a button - its label is the edge's action label
 * (rename "Suspend" in the Status Engine and the console button follows).
 * Firing posts the explicit transition; the backend enforces the strict
 * graph + edge roles. The platform tenant is excluded from all lifecycle
 * actions; archive keeps data (soft) - hard purge is BL-035.
 */

function edgeIcon(target: StatusNodeData | undefined) {
  if (target?.isArchived) return Archive;
  if (target?.blocksAccess) return CirclePause;
  return CirclePlay;
}

function edgeDescription(target: StatusNodeData | undefined): string {
  if (!target) return 'Moves the tenant along the status flow.';
  if (target.isArchived)
    return `Moves the tenant to "${target.label}" - sign-in is blocked and it leaves the default list. Data stays intact (no hard delete).`;
  if (target.blocksAccess)
    return `Moves the tenant to "${target.label}" - its users are blocked from signing in (active sessions end on their next request). Data stays intact.`;
  return `Moves the tenant to "${target.label}" - sign-in is allowed again.`;
}

/**
 * Other Action icons under the Foundryx UIUX switch (one icon per meaning);
 * the lifecycle edges keep their own drawn icons.
 */
export const TENANT_FX_ICONS: Record<string, FxIconRef> = {
  edit: 'edit',
  'open-tenant': <ExternalLink aria-hidden="true" className="size-[18px]" />,
  purge: 'trash',
};

/**
 * What the Foundryx UIUX purge confirm asks to type (owner decision: the
 * record's name or number replaces the press and hold): one tenant types its
 * slug, several type how many there are. With the switch off the confirm
 * keeps `expected` (the slug, or DELETE for several).
 */
export function fxPurgeExpected(rows: Pick<TenantListItem, 'slug'>[]): string {
  return rows.length === 1 ? rows[0].slug : String(rows.length);
}

export function useTenantActions(): ResourceAction<TenantListItem>[] {
  const router = useRouter();
  const fx = useFx();
  const byWhom = useSession().data?.user?.name ?? undefined;
  const [graph, setGraph] = useState<StatusGraph | null>(null);

  // The tenant entity's edge graph drives the lifecycle buttons. Fetched via
  // the console's own endpoint (tenants.read) so operators never need
  // statuses.read for lifecycle actions (code-review fix). Fail quiet -
  // Edit/Open remain; lifecycle buttons just don't render.
  useEffect(() => {
    let cancelled = false;
    tenantAdminService
      .statusGraph()
      .then((data) => !cancelled && setGraph(data))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  return useMemo<ResourceAction<TenantListItem>[]>(() => {
    const statusById = new Map((graph?.statuses ?? []).map((s) => [s.id, s]));
    const transitions = [...(graph?.transitions ?? [])].sort(
      (a, b) => a.sortOrder - b.sortOrder,
    );

    // Actions group by LABEL, not edge (sprint-2/02 review feedback): the
    // same semantic action ("Archive") often exists from several statuses
    // via DIFFERENT edges - a mixed Active+Suspended selection still bulk-
    // archives, each row firing ITS own edge.
    const edgesByLabel = new Map<string, StatusTransition[]>();
    for (const edge of transitions) {
      const group = edgesByLabel.get(edge.label);
      if (group) group.push(edge);
      else edgesByLabel.set(edge.label, [edge]);
    }

    // The edge THIS row would fire for the action - D4 (must leave the row's
    // current status) + rule-engine D6 (server-computed fireable ids while
    // conditions exist; record-specific, not derivable from the shared graph).
    const edgeForRow = (edges: StatusTransition[], t: TenantListItem) =>
      edges.find(
        (e) =>
          t.statusId === e.fromStatusId &&
          (t.availableTransitionIds == null ||
            t.availableTransitionIds.includes(e.id)),
      );

    // The tenant-lifecycle status entity is PLATFORM-OWNED (a single global
    // graph, no per-tenant fork) with system-locked keys (label/color are
    // editable, `key` is not) - so the three seeded target keys below always
    // resolve to the SAME status row regardless of a renamed label, and
    // `TenantService.archive/suspend/reactivate` (edge-agnostic, key-keyed
    // lookups) are safe deferred-action handlers for them (sprint-4/23, T5,
    // D2). An OPERATOR-ADDED custom status sharing a label ("Dormant" also
    // reading "Archive") but a DIFFERENT key falls through to `confirm:` -
    // disclosed 4th carve-out (see the T5 report); a fully general fix needs
    // a per-row-payload `tenants.transition` deferred action (backlog).
    const DEFERRED_KEY_FOR_TARGET: Record<string, string> = {
      archived: 'tenants.archive',
      suspended: 'tenants.suspend',
      active: 'tenants.reactivate',
    };

    const transitionAction = (
      label: string,
      edges: StatusTransition[],
    ): ResourceAction<TenantListItem> => {
      const target = statusById.get(edges[0].toStatusId);
      const deferredActionKey = target ? DEFERRED_KEY_FOR_TARGET[target.key] : undefined;
      const common = {
        id: `transition-${edges[0].id}`,
        label,
        icon: edgeIcon(target),
        tone: target?.isArchived ? ('destructive' as const) : undefined,
        // Legacy privilege boundary by TARGET flags (mirrors the backend):
        // archive-like → tenants.archive, everything else → tenants.suspend.
        permission: target?.isArchived ? 'tenants.archive' : 'tenants.suspend',
        surfaces: { row: true, bulk: true },
        isVisible: (rows: TenantListItem[]) =>
          rows.length > 0 &&
          rows.every((t) => !t.isPlatform && Boolean(edgeForRow(edges, t))),
      };
      // Fix round 1 item 12: a `deferred` action has no `run` - the server's
      // registered handler (`tenants.archive/suspend/reactivate`) commits it,
      // never this frontend function. Built as two FULLY separate branches
      // (rather than spreading `deferred`/`confirm` onto one object that
      // always carried `run`) so the dead-when-deferred `run` body can't
      // exist at all, and the type (a discriminated union) rejects supplying
      // both.
      if (deferredActionKey) {
        return {
          ...common,
          deferred: {
            actionKey: deferredActionKey,
            entityType: 'tenant',
            // Foundryx UIUX switch only: the one-tenant countdown names it.
            fxName: (rows: TenantListItem[]) => (rows.length === 1 ? rows[0].name : undefined),
          },
        };
      }
      return {
        ...common,
        confirm: {
          title: `${label} this tenant?`,
          description: edgeDescription(target),
          confirmLabel: `${label} tenant`,
        },
        run: async (rows, rt) => {
          // Count what actually FIRED (code-review fix): a row whose edge
          // vanished between the visibility check and run (concurrent rule/
          // status change) is skipped, not silently counted as updated.
          const fired = (
            await Promise.all(
              rows.map(async (t) => {
                const edge = edgeForRow(edges, t);
                if (!edge) return false;
                await tenantAdminService.transition(t.id, edge.id);
                return true;
              }),
            )
          ).filter(Boolean).length;
          const skipped = rows.length - fired;
          if (fx) {
            toast.fxDone({
              what:
                fired === 1 && rows.length === 1
                  ? `${label}: ${rows[0].name}`
                  : `${label}: ${fired} ${fired === 1 ? 'tenant' : 'tenants'}`,
              howMany: skipped > 0 ? `${skipped} skipped, no longer eligible` : undefined,
              byWhom,
            });
          } else if (skipped > 0) {
            toast.warning(
              `${label}: ${fired} updated, ${skipped} skipped (no longer eligible).`,
            );
          } else {
            toast.success(`${label}: ${fired} tenant(s) updated.`);
          }
          rt.reload();
        },
      };
    };

    // Hard delete (BL-035) - ARCHIVED rows only, irreversible, typed confirm
    // (module-uninstall UX): single row types the slug, bulk types DELETE.
    // Archived = the ENGINE FLAG on the row's status (code-review fix: the
    // legacy category string diverges for custom archived-flagged statuses -
    // a 'Dormant' tenant sits in the Archived view but isn't 'ARCHIVED').
    const rowIsArchived = (t: TenantListItem) =>
      t.statusId
        ? Boolean(statusById.get(t.statusId)?.isArchived)
        : t.status === 'ARCHIVED';
    const deleteAction: ResourceAction<TenantListItem> = {
      id: 'purge',
      label: 'Delete permanently',
      icon: Trash2,
      tone: 'destructive',
      permission: 'tenants.delete',
      surfaces: { row: true, bulk: true },
      isVisible: (rows) =>
        rows.length > 0 && rows.every((t) => !t.isPlatform && rowIsArchived(t)),
      confirm: {
        // Foundryx UIUX switch: the question names its object, one line says
        // what does not come back, the action is verb + object. Off keeps
        // today's words.
        title: fx
          ? (rows) =>
              rows.length === 1
                ? `Delete ${rows[0].name} permanently?`
                : `Delete ${rows.length} tenants permanently?`
          : 'Delete permanently?',
        description: fx
          ? 'Users, roles, settings and module data are erased and do not come back.'
          : 'This erases the tenant and ALL its data - users, roles, settings, module data. It cannot be undone (archive already blocks sign-in; delete only when the data is truly disposable).',
        confirmLabel: fx
          ? (rows) => (rows.length === 1 ? 'Delete tenant' : `Delete ${rows.length} tenants`)
          : 'Delete forever',
        fxKeepLabel: (rows) => (rows.length === 1 ? 'Keep tenant' : 'Keep tenants'),
        input: {
          fxExpected: fxPurgeExpected,
          expected: (rows) => (rows.length === 1 ? rows[0].slug : 'DELETE'),
          hint: (rows) =>
            rows.length === 1
              ? `Type the tenant slug "${rows[0].slug}" to confirm.`
              : `Type "DELETE" to erase ${rows.length} tenants.`,
        },
      },
      run: async (rows, rt) => {
        await Promise.all(
          rows.map((t) => tenantAdminService.purge(t.id, t.slug)),
        );
        // No Undo: a purge erases the tenant, nothing in the API brings it back.
        if (fx) {
          toast.fxDone({
            what:
              rows.length === 1
                ? `Tenant ${rows[0].slug} deleted permanently`
                : `${rows.length} tenants deleted permanently`,
            byWhom,
          });
        } else {
          toast.success(`Deleted ${rows.length} tenant(s) permanently.`);
        }
        rt.reload();
      },
    };

    return [
      {
        id: 'edit',
        label: 'Edit',
        icon: Pencil,
        permission: 'tenants.update',
        surfaces: { row: true },
        run: ([tenant], rt) => {
          if (!tenant) return;
          router.push(
            tenantFormHref(tenant.id, {
              ctx: rt.ctx,
              index: rt.index,
              edit: true,
            }),
          );
        },
      },
      {
        id: 'open-tenant',
        label: 'Open tenant',
        icon: ExternalLink,
        permission: 'tenants.read',
        surfaces: { row: true, form: true },
        // Suspended/archived tenants reject sign-in anyway.
        isVisible: (rows) => rows.length === 1 && rows[0].status === 'ACTIVE',
        run: ([tenant]) => {
          if (!tenant) return;
          // Same domain, tenant's subdomain (plan 07 §6). Operator
          // login-as-admin is BL-047 - this opens the tenant's sign-in.
          window.open(
            tenantUrl(tenant.slug, window.location),
            '_blank',
            'noopener',
          );
        },
      },
      ...Array.from(edgesByLabel, ([label, edges]) =>
        transitionAction(label, edges),
      ),
      deleteAction,
    ];
  }, [router, graph, fx, byWhom]);
}
