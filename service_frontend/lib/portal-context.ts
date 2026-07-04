import type {
  PortalSurface,
  PortalSurfaceContext,
} from '@/services/portal-surface-service';

/**
 * Portal context helpers (Cluster E, slice 0b). A "context" is a scoped
 * membership (`scopeType`/`scopeId`) that a surface's data is narrowed to. The
 * global event/context filter pill (AC-06-25) operates over the UNION of these
 * across all accessible surfaces.
 */

/** A unique context key (stable across surfaces) for the filter pill + matching. */
export function contextKey(ctx: PortalSurfaceContext): string {
  return `${ctx.scopeType}:${ctx.scopeId ?? ''}`;
}

/**
 * The backend `contextId` (an event/project scope id) for the active filter key
 * (AC-06-25), or null when there is no event to narrow to. A context key is
 * `<scopeType>:<scopeId>`; only a `project` scope carries an event id the review
 * surfaces filter by. A tenant-wide scope / no active filter → null (the surface
 * loads across all contexts).
 */
export function activeContextScopeId(activeContextKey: string | null): string | null {
  if (!activeContextKey) return null;
  const sep = activeContextKey.indexOf(':');
  if (sep < 0) return null;
  const scopeType = activeContextKey.slice(0, sep);
  const scopeId = activeContextKey.slice(sep + 1);
  if (scopeType !== 'project' || !scopeId) return null;
  return scopeId;
}

/**
 * A human label for a context. Prefers the server-resolved event name
 * (AC-06-25 — `ctx.label`); falls back to "Tenant-wide" for a tenant scope and a
 * short-id "Event {…}" only when the name is unresolvable. Deterministic.
 */
export function contextLabel(ctx: PortalSurfaceContext): string {
  if (ctx.scopeType === 'tenant' || !ctx.scopeId) return 'Tenant-wide';
  if (ctx.label) return ctx.label;
  const shortId = ctx.scopeId.slice(0, 8);
  return `Event ${shortId}`;
}

export interface PortalContextOption {
  key: string;
  label: string;
  context: PortalSurfaceContext;
}

/** The de-duplicated union of every surface's contexts, sorted by label. */
export function unionContexts(surfaces: PortalSurface[]): PortalContextOption[] {
  const seen = new Map<string, PortalContextOption>();
  for (const surface of surfaces) {
    for (const ctx of surface.contexts) {
      const key = contextKey(ctx);
      if (!seen.has(key)) {
        seen.set(key, { key, label: contextLabel(ctx), context: ctx });
      }
    }
  }
  return Array.from(seen.values()).sort((a, b) => a.label.localeCompare(b.label));
}

/** Surfaces whose contexts include the active filter (or all when unfiltered). */
export function filterSurfaces(
  surfaces: PortalSurface[],
  activeContextKey: string | null,
): PortalSurface[] {
  if (!activeContextKey) return surfaces;
  return surfaces.filter((s) =>
    s.contexts.some((c) => contextKey(c) === activeContextKey),
  );
}

/** A surface's contexts narrowed to the active filter (or all when unfiltered). */
export function contextsForSurface(
  surface: PortalSurface,
  activeContextKey: string | null,
): PortalSurfaceContext[] {
  if (!activeContextKey) return surface.contexts;
  return surface.contexts.filter((c) => contextKey(c) === activeContextKey);
}
