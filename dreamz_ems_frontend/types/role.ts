/**
 * Role domain types (plan 03). A Role carries a set of permission keys; users
 * gain a permission by holding a role that grants it. The lightweight `Role`
 * (id + name) in `types/user.ts` stays the assignment ref; these are the richer
 * management shapes for the Roles list + detail form.
 */
import type { UserStatus } from './user';

/** Row in the Roles list — identity + computed counts. */
export interface RoleListItem {
  id: string;
  name: string;
  description: string | null;
  /** Seeded/system role — cannot be deleted (name/desc/permissions still editable). */
  isSystem: boolean;
  /** Computed server-side (assigned users). */
  userCount: number;
  /** Computed server-side (granted permission keys). */
  permissionCount: number;
  createdAt: string; // ISO
}

/** Full role record for the detail form — adds the granted permission keys. */
export interface RoleDetail extends RoleListItem {
  permissionKeys: string[];
}

/** Create payload — role + its grants in one transaction (implied-read normalized server-side). */
export interface CreateRoleInput {
  name: string;
  description?: string | null;
  permissionKeys: string[];
  isSystem?: boolean;
}

/** Patch payload — `permissionKeys` (when present) replaces the whole grant set. */
export interface UpdateRoleInput {
  name?: string;
  description?: string | null;
  permissionKeys?: string[];
  isSystem?: boolean;
}

/** A user assigned to a role (Assigned Users tab + the mirror of Users→roles). */
export interface RoleUser {
  id: string;
  name: string | null;
  email: string;
  avatar: string | null;
  status: UserStatus;
  assignedAt: string; // ISO — "Joined"/assigned-at
}

/** A tenant user not yet holding the role — option in the "Assign user" picker. */
export interface AssignableUser {
  id: string;
  name: string | null;
  email: string;
  avatar: string | null;
  status: UserStatus;
}
