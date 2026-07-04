/**
 * Persona RBAC wire types (Cluster E, slice 0b — AC-06-26). The EMS
 * Profile-persona system, separate from staff core RBAC. camelCase to match the
 * backend `persona_schemas.py` (ApiModel).
 */

/** A tenant-configurable Profile role. System personas are delete-locked. */
export interface Persona {
  id: string;
  key: string;
  label: string;
  description: string | null;
  isSystem: boolean;
  sortOrder: number;
  createdAt: string;
}

export interface PersonaInput {
  key: string;
  label?: string;
  description?: string;
  sortOrder?: number;
}

export interface PersonaPatch {
  key?: string;
  label?: string;
  description?: string;
  sortOrder?: number;
}

/** A grantable portal-permission key (the catalog the grant editor lists). */
export interface PortalPermission {
  key: string;
  label: string;
  description: string;
}

/** A scoped persona membership on a Profile. */
export interface PersonaMembership {
  id: string;
  profileId: string;
  personaId: string;
  scopeType: string;
  scopeId: string | null;
  grantedVia: string;
  createdAt: string;
}

export interface PersonaMembershipInput {
  personaId: string;
  /** 'tenant' (default) | 'project'. */
  scopeType?: string;
  /** Required for project scope. */
  scopeId?: string;
}

/**
 * Staff "Send portal invite" payload (AC-06-15c). All optional — a plain invite
 * carries no grant; a persona + context grants it on acceptance.
 */
export interface PortalInviteInput {
  /** A persona KEY to grant on acceptance (granted_via=INVITE). */
  personaKey?: string;
  /** 'tenant' (default) | 'project'. */
  scopeType?: string;
  /** Required for project scope. */
  scopeId?: string;
}

export interface PortalInviteResult {
  sent: boolean;
  email: string;
}
