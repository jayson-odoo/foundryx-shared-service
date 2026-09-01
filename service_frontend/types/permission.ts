/**
 * Permission catalog types - the dynamic RBAC catalog (plan 03 §2). A permission
 * is a flat key `"<resource>.<action>"`. Modules (core + App-Store) declare their
 * own permissions via a CSV synced into the backend `permissions` table; this is
 * the shape the catalog endpoint returns to drive the role Permissions tab.
 */

/** One grantable action on a resource (e.g. `users.create`). */
export interface PermissionAction {
  /** Flat permission key - `"<resource>.<action>"`. */
  key: string;
  /** Action segment - `read | create | update | delete | <custom>`. */
  action: string;
  /** Human label shown as the dropdown option (e.g. "Create"). */
  actionLabel: string;
  description: string | null;
}

/** A resource (a matrix row) and its available actions, owned by a module. */
export interface PermissionResource {
  /** Resource segment of the key (e.g. `users`). */
  resource: string;
  /** Heading shown for this resource row (e.g. "User Management"). */
  resourceLabel: string;
  /** Owning module - `core` or an App-Store module name (groups the sections). */
  module: string;
  actions: PermissionAction[];
}

/** The catalog, flat list of resources; the UI groups by `module` for display. */
export type PermissionCatalog = PermissionResource[];
