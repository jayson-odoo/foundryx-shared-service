/**
 * Tenant administration types (plan 07 - Platform Console). These are the
 * platform-operator management shapes for the Tenants list + detail form.
 * Since sprint-2/01 the lifecycle is status-engine-driven: `status` is a
 * legacy uppercase wire value; `statusLabel`/`statusColor` are the display
 * fields to render (operator-editable, custom statuses included).
 */

/** Seeded lifecycle wire values - display fallback only (engine drives behavior). */
export type TenantLifecycle = 'ACTIVE' | 'SUSPENDED' | 'ARCHIVED';

/** Row in the Tenants list. */
export interface TenantListItem {
  id: string;
  name: string;
  /** URL identity (subdomain) - immutable after creation. */
  slug: string;
  status: TenantLifecycle | (string & {});
  /** Engine-driven display (sprint-2/01) - render these when present. */
  statusId?: string | null;
  statusLabel?: string | null;
  statusColor?: string | null;
  /**
   * Per-record fireable edge ids (sprint-2/02 rule engine) - present only
   * while a conditioned tenant edge exists; null = derive from statusId.
   */
  availableTransitionIds?: string[] | null;
  /** The reserved operator tenant - cannot be suspended/archived. */
  isPlatform: boolean;
  contactName: string | null;
  contactEmail: string | null;
  /** Schema-ready; CNAME/infra wiring is BL-034. */
  customDomain: string | null;
  /** Computed server-side - users belonging to the tenant. */
  userCount: number;
  createdAt: string; // ISO
}

/** Full tenant record for the detail form. */
export interface TenantDetail extends TenantListItem {
  notes: string | null;
  updatedAt: string; // ISO
}

/** Provision payload - tenant + its first admin user in one transaction (plan 07 §7). */
export interface ProvisionTenantInput {
  name: string;
  slug: string;
  contactName?: string | null;
  contactEmail?: string | null;
  notes?: string | null;
  /** First admin user (operator-set temp password, handed out-of-band - BL-033). */
  adminName: string;
  adminEmail: string;
  adminPassword: string;
}

/** Patch payload - slug is immutable, lifecycle moves via explicit actions. */
export interface UpdateTenantInput {
  name?: string;
  contactName?: string | null;
  contactEmail?: string | null;
  customDomain?: string | null;
  notes?: string | null;
}
