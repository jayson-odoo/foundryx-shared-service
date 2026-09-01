/**
 * Omnichannel media-caps settings service - the boundary the UI talks to (plan
 * 12 Slice 3, AC-12-23). Frontend-first bound the mock; Phase B swaps
 * `omnichannelSettingsService` to the real api-client impl in ONE line (bottom).
 * The interface IS the backend contract (`GET/PUT /omnichannel/settings`).
 */
import { realOmnichannelSettingsService } from './omnichannel-settings-service.real';

/** The media kinds returned in `effective` (VOICE shares AUDIO's editable cap). */
export type MediaKind = 'IMAGE' | 'VIDEO' | 'AUDIO' | 'VOICE' | 'DOCUMENT' | 'STICKER';

/** Resolved cap + Meta ceiling + fixed accepted mimes for one media kind. */
export interface MediaCapEffective {
  /** Effective cap in bytes = min(configured override, Meta ceiling). */
  maxBytes: number;
  /** Meta's hard ceiling in bytes (an override can never exceed this). */
  ceilingBytes: number;
  /** Fixed accepted MIME types (read-only, not tenant-editable). */
  acceptedMimes: string[];
}

/** The five editable per-type size caps (bytes). `null` = no override (Meta default). */
export interface OmnichannelSettingsOverrides {
  imageMaxBytes: number | null;
  videoMaxBytes: number | null;
  audioMaxBytes: number | null;
  documentMaxBytes: number | null;
  stickerMaxBytes: number | null;
}

/** Full settings payload for a scope (workspace or tenant-default). */
export interface OmnichannelSettings {
  /** `null` = the tenant-wide default row. */
  workspaceId: string | null;
  overrides: OmnichannelSettingsOverrides;
  effective: Record<MediaKind, MediaCapEffective>;
}

/**
 * Update body: an omitted key keeps the current override; an explicit `null`
 * clears it (→ Meta ceiling); a number sets a cap (backend clamps ≤ ceiling).
 */
export type OmnichannelSettingsUpdate = Partial<OmnichannelSettingsOverrides>;

export interface OmnichannelSettingsService {
  /** Read settings for a workspace, or the tenant default when `workspaceId` is omitted. */
  get(workspaceId?: string | null): Promise<OmnichannelSettings>;
  /** Persist per-type overrides for a workspace / the tenant default. */
  update(
    overrides: OmnichannelSettingsUpdate,
    workspaceId?: string | null,
  ): Promise<OmnichannelSettings>;
}

// Phase B: real api-client implementation. (Mock retained in *.mock.ts.)
export const omnichannelSettingsService: OmnichannelSettingsService =
  realOmnichannelSettingsService;
