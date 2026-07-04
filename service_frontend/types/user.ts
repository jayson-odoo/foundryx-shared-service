/**
 * User domain types. Mirrors the backend `User` shape (app/models/user.py),
 * extended with the multi-role model decided in plan 02 (roles[] replaces the
 * single roleId). Kept framework-agnostic so services + UI share one source.
 */

/** Lifecycle status. INVITED is system-managed (set on create, cleared on set-password). */
export type UserStatus = 'ACTIVE' | 'INACTIVE' | 'BLOCKED' | 'INVITED';

/** A role is identity-only for now (name + id); RBAC/permissions are backlog BL-009. */
export interface Role {
  id: string;
  name: string;
}

export interface User {
  id: string;
  tenantId: string;
  name: string | null;
  email: string;
  status: UserStatus;
  avatar: string | null;
  roles: Role[];
  createdAt: string; // ISO — "Joined"
  lastSignInAt: string | null;
  emailVerifiedAt: string | null;
  isTrashed: boolean;
}

/** Payload to create a user (invite flow — no password; status becomes INVITED). */
export interface CreateUserInput {
  name: string;
  email: string;
  roleIds: string[];
  status: Exclude<UserStatus, 'INVITED'>; // INVITED is assigned by the create flow
}

/** Patch payload for the single global form save. Email = admin instant path
 * (plan sprint-2/04): actor ≠ target only — own email rides the /account
 * ceremony (backend 409s a self-change). */
export interface UpdateUserInput {
  name?: string;
  email?: string;
  roleIds?: string[];
  status?: Exclude<UserStatus, 'INVITED'>;
}
