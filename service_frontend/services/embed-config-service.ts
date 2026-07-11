/**
 * Embed-access config service — the boundary the embed-settings screen talks to
 * (plan 11H, tenant-level embed connection admin). The UI reads/writes ONLY
 * through this interface (via `useEmbedConfig`); it never touches api-client.
 *
 * The interface IS the backend contract (`/omnichannel/embed-config*`, gated
 * `workspaces.manage`). Frontend-first built against `.mock`; the shipped screen
 * binds `.real` (bottom).
 */
import { realEmbedConfigService } from './embed-config-service.real';

/** A workspace pick for the iframe-snippet workspace selector. */
export interface EmbedWorkspaceOption {
  id: string;
  name: string;
}

/** The tenant's embed-access state. The `embedSecret` is NEVER present here —
 * `hasSecret` only reports whether one is set (revealed once at rotate). */
export interface EmbedConfig {
  /** `null` until the tenant enables embed access. Also the `?c=` / assertion `iss`. */
  connectionId: string | null;
  allowedOrigins: string[];
  hasSecret: boolean;
  /** Public backend origin — used to build the iframe snippet. */
  host: string;
  workspaces: EmbedWorkspaceOption[];
}

/** The freshly-minted secret — returned EXACTLY ONCE (write-only after). */
export interface EmbedRotateSecretResult {
  embedSecret: string;
}

export interface EmbedConfigService {
  /** Read the tenant's embed-access state. */
  get(): Promise<EmbedConfig>;
  /** Create the embed connection if absent (idempotent). Returns the fresh state. */
  enable(): Promise<EmbedConfig>;
  /** Generate + store a new secret; returns the plaintext ONCE. */
  rotateSecret(): Promise<EmbedRotateSecretResult>;
  /** Replace the allowed parent origins (server validates + dedupes). */
  setOrigins(allowedOrigins: string[]): Promise<EmbedConfig>;
}

// Phase B: real api-client implementation. (Mock retained in *.mock.ts.)
export const embedConfigService: EmbedConfigService = realEmbedConfigService;
