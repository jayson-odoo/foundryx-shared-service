/**
 * Ideation iframe-embed connection types (PLAN-ideation-embed-sso §7, AC-E-5/12).
 *
 * Mirrors the backend `app_ideation.embed_connections` admin contract
 * (`modules/ideation/routers/embed_admin.py`). One row per host application
 * (e.g. sorento) authorised to embed a tenant's Ideas workspace. The
 * `signingSecret` is WRITE-ONLY — accepted on create/rotate, never returned by
 * any read (the item only reports `hasSecret`). The admin holds the plaintext it
 * supplied and reveals it once client-side, then pastes it into the host's embed
 * config. Kept framework-agnostic so the service + UI share one source.
 *
 * NOTE: the backend admin router returns snake_case JSON (a plain pydantic
 * `BaseModel`, not the camelCase `ApiModel`); the real service maps it to this
 * camelCase shape (see `embed-connection-service.real.ts`).
 */

/** An embed connection as surfaced to the management UI (never the plaintext). */
export interface EmbedConnectionItem {
  /** The shared, non-secret handle the host sends in its embed session body. */
  connectionId: string;
  tenantId: string;
  /** Browser origins permitted to iframe the workspace. */
  allowedOrigins: string[];
  /** Optional scope to one core Product (null = all the tenant's ideas). */
  productId: string | null;
  isActive: boolean;
  /** True once a signing secret is stored (the secret itself is never returned). */
  hasSecret: boolean;
  createdAt: string | null; // ISO
  updatedAt: string | null; // ISO
}

/** Create payload. `signingSecret` is generated/typed client-side, ≥ 8 chars. */
export interface EmbedConnectionCreateInput {
  connectionId: string;
  signingSecret: string;
  allowedOrigins: string[];
  productId?: string | null;
  isActive?: boolean;
}
