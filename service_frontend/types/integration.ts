/**
 * Integration framework types (plan 09) — the core "connections" primitives
 * every external-service integration plugs into. SMTP (email) is the first
 * provider; future providers (storage, LLM, ERP) reuse these shapes, whether
 * they ship in core or as App Store modules.
 */

/** Integration category — drives grouping/iconography, not behavior. */
export type IntegrationType =
  | 'email'
  | 'storage'
  | 'llm'
  | 'erp'
  | 'payment'
  | 'consumer'
  // Meetings module (S0): the calendar reader and the notetaker bot account.
  // Two categories, not one, because the one-active-per-type invariant must
  // let a tenant hold BOTH at once.
  | 'calendar'
  | 'meeting_bot';

/** Connection health — UNVERIFIED until a test passes, ERROR on failures. */
export type ConnectionStatus = 'ACTIVE' | 'UNVERIFIED' | 'ERROR';

/** One wizard form field, declared by the provider (drives the configure step). */
export interface ProviderField {
  /** Key in `config` (or `credentials` when `secret`). */
  key: string;
  label: string;
  type: 'text' | 'number' | 'password' | 'select';
  required: boolean;
  /** Secret values go to encrypted `credentials` and are write-only. */
  secret?: boolean;
  placeholder?: string;
  /** Select options (type === 'select'). */
  options?: Array<{ value: string; label: string }>;
  defaultValue?: string;
  /** Collapsed under the wizard's "Advanced" section. */
  advanced?: boolean;
}

/** Catalog entry (GET /integrations/providers) — config schema drives the wizard. */
export interface IntegrationProvider {
  /** API identity, e.g. "smtp". */
  provider: string;
  type: IntegrationType;
  title: string;
  description: string;
  /** Lucide icon key (graceful fallback for unknowns). */
  icon: string | null;
  fields: ProviderField[];
  /** Label for the OPTIONAL targeted test, e.g. "Send test email". The default
   *  test is always a plain connection check (connect + authenticate). */
  testLabel: string;
  /** Present = the provider offers an optional targeted test (SMTP: send a
   *  real email to an address). Null = connection check only. */
  testTarget: { label: string; placeholder: string } | null;
}

/** A tenant's configured connection — credentials are NEVER returned. */
export interface Connection {
  id: string;
  tenantId: string;
  provider: string;
  type: IntegrationType;
  name: string;
  /** Non-secret config only (host, port, fromEmail, …). */
  config: Record<string, string>;
  status: ConnectionStatus;
  /** Storage write-target flag — exactly one active storage connection per
   * tenant; new uploads land there, resolve-by-type serves it. */
  isActive: boolean;
  lastTestedAt: string | null; // ISO
  lastError: string | null;
  /** Outbox dispatcher throttle (plan 09 §5 — low-spec SMTP guard). */
  rateLimitPerMinute: number;
  createdAt: string; // ISO
  updatedAt: string; // ISO
}

/** Create/update payload — secrets travel separately, write-only. */
export interface ConnectionInput {
  provider: string;
  name: string;
  config: Record<string, string>;
  /** Encrypted at rest; on update an OMITTED key means "keep existing". */
  credentials: Record<string, string>;
  rateLimitPerMinute?: number;
}

/** Inline test outcome (wizard test step / card Test action). */
export interface TestConnectionResult {
  ok: boolean;
  message: string;
  checkedAt: string; // ISO
}

/** Display state for the integration card StatusBadge (derived, not stored). */
export type ConnectionBadge = 'NOT_CONNECTED' | 'CONNECTED' | 'UNVERIFIED' | 'ERROR';

export function connectionBadge(c: Connection | undefined): ConnectionBadge {
  if (!c) return 'NOT_CONNECTED';
  if (c.status === 'ACTIVE') return 'CONNECTED';
  return c.status;
}
