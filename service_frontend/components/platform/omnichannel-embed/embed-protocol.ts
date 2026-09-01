/**
 * Omnichannel embed - postMessage protocol v1 (cross-repo contract
 * `11-omnichannel-embed-contract.md` §5) + the `/embed/session` wire types
 * (§3). Shared by the embed shell + its hook. NO `any` - every envelope,
 * claim set and session field is explicitly typed.
 *
 * The widget (this repo, rendered in an iframe) and the parent (the consumer
 * frontend, e.g. EMS) exchange `{ v:1, type, payload }` envelopes. Every
 * RECEIVE validates `event.origin`; no `'*'` is ever accepted inbound.
 */

/** Protocol version carried on every envelope; a breaking change bumps this. */
export const PROTOCOL_VERSION = 1;

/** Widget → parent message types. */
export type WidgetOutboundType = 'ready' | 'needToken' | 'resize' | 'activity';
/** Parent → widget message types. */
export type ParentInboundType = 'init' | 'theme' | 'token';

export interface EmbedEnvelope<T> {
  v: typeof PROTOCOL_VERSION;
  type: WidgetOutboundType | ParentInboundType;
  payload: T;
}

/** `colorScheme` on init/theme - the light/dark toggle the parent controls. */
export type EmbedColorScheme = 'light' | 'dark';

/**
 * Whitelisted brand primitives the parent may push (contract §5). Friendly
 * aliases map to concrete CSS custom properties (see `THEME_VAR_MAP`); `vars`
 * is an escape hatch for raw `--foundryx-*` overrides applied verbatim, mirroring
 * the BrandingProvider idiom. Only known aliases / `--`-prefixed vars are
 * applied - an unknown key is ignored (foolproof: no runtime surprise).
 */
export interface EmbedTheme {
  primary?: string;
  primaryActive?: string;
  surface?: string;
  surfaceSoft?: string;
  text?: string;
  bubbleIn?: string;
  bubbleOut?: string;
  radius?: string;
  /** Raw CSS custom properties (keys MUST start with `--`) applied as-is. */
  vars?: Record<string, string>;
}

/** Parent → widget payloads. */
export interface InitPayload {
  assertion: string;
  theme?: EmbedTheme;
  colorScheme?: EmbedColorScheme;
}
export interface ThemePayload {
  theme?: EmbedTheme;
  colorScheme?: EmbedColorScheme;
}
export interface TokenPayload {
  assertion: string;
}

/** Widget → parent payloads. */
export interface ReadyPayload {
  /** empty - the widget is mounted and requesting `init`. */
  [k: string]: never;
}
export interface ResizePayload {
  height: number;
}
export type ActivityKind = 'message_sent' | 'message_received' | 'assigned';
/** Coarse "something happened" - NEVER message content (contract §5). */
export interface ActivityPayload {
  kind: ActivityKind;
  contactId: string | null;
}

/**
 * The claims the widget decodes CLIENT-SIDE from the assertion JWT (base64url
 * payload - NO signature verification here; the shared service verifies). Used
 * only to learn `allowedOrigins` so an inbound `init` origin can be validated.
 */
export interface EmbedAssertionClaims {
  allowedOrigins: string[];
  scope: string;
  workspaceId: string;
}

/** `/embed/session` success body (contract §3). */
export interface EmbedAgent {
  id: string;
  name: string;
  avatarUrl?: string | null;
}
export interface EmbedWorkspace {
  id: string;
  name: string;
}
export interface EmbedSessionResponse {
  accessToken: string;
  expiresIn: number;
  agent: EmbedAgent;
  workspace: EmbedWorkspace;
  /** `"inbox"` (whole workspace) or `"thread:<contactId>"` (single thread). */
  scope: string;
  caps: string[];
}

/** CSS custom properties each friendly theme alias lands on. */
export const THEME_VAR_MAP: Record<
  Exclude<keyof EmbedTheme, 'vars'>,
  string[]
> = {
  primary: ['--primary', '--foundryx-primary'],
  primaryActive: ['--foundryx-primary-active'],
  surface: ['--background', '--foundryx-light'],
  surfaceSoft: ['--foundryx-light-soft'],
  text: ['--foreground', '--foundryx-dark'],
  bubbleIn: ['--embed-bubble-in'],
  bubbleOut: ['--embed-bubble-out'],
  radius: ['--embed-radius'],
};

/** Resolve the flat set of CSS custom properties a theme produces. */
export function themeToCssVars(theme: EmbedTheme | undefined): Record<string, string> {
  const out: Record<string, string> = {};
  if (!theme) return out;
  for (const [alias, cssVars] of Object.entries(THEME_VAR_MAP)) {
    const value = theme[alias as keyof EmbedTheme];
    if (typeof value !== 'string' || !value) continue;
    for (const cssVar of cssVars) out[cssVar] = value;
  }
  if (theme.vars) {
    for (const [key, value] of Object.entries(theme.vars)) {
      // Only accept genuine custom properties - never a bare identifier that
      // could collide with a real style declaration.
      if (key.startsWith('--') && typeof value === 'string') out[key] = value;
    }
  }
  return out;
}

/** Decode a base64url segment to a UTF-8 string (browser `atob`). */
function decodeBase64Url(segment: string): string {
  const padded = segment.replace(/-/g, '+').replace(/_/g, '/');
  const withPad = padded + '='.repeat((4 - (padded.length % 4)) % 4);
  return atob(withPad);
}

/**
 * Decode the assertion JWT's payload to read `allowedOrigins` (+ scope /
 * workspaceId). Returns null on any malformed input - the caller treats a null
 * as "cannot validate → reject". No signature check (server-side only).
 */
export function decodeAssertionClaims(jwt: string): EmbedAssertionClaims | null {
  if (typeof jwt !== 'string') return null;
  const parts = jwt.split('.');
  if (parts.length !== 3) return null;
  try {
    const raw = JSON.parse(decodeBase64Url(parts[1])) as Record<string, unknown>;
    const allowedOrigins = Array.isArray(raw.allowedOrigins)
      ? raw.allowedOrigins.filter((o): o is string => typeof o === 'string')
      : [];
    if (allowedOrigins.length === 0) return null;
    return {
      allowedOrigins,
      scope: typeof raw.scope === 'string' ? raw.scope : '',
      workspaceId: typeof raw.workspaceId === 'string' ? raw.workspaceId : '',
    };
  } catch {
    return null;
  }
}

/** True when `type` is a recognised inbound (parent → widget) message. */
export function isEnvelope(data: unknown): data is EmbedEnvelope<unknown> {
  if (typeof data !== 'object' || data === null) return false;
  const env = data as Record<string, unknown>;
  return env.v === PROTOCOL_VERSION && typeof env.type === 'string';
}

/** `"thread:<contactId>"` → the contact id, else null (e.g. `"inbox"`). */
export function contactIdFromScope(scope: string): string | null {
  if (!scope.startsWith('thread:')) return null;
  const id = scope.slice('thread:'.length);
  return id || null;
}
