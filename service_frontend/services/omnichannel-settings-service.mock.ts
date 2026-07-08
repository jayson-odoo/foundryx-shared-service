/**
 * PHASE 1 MOCK — in-memory omnichannel media-caps settings (plan 12 Slice 3).
 * Deterministic ceilings/mimes mirror the backend (`media_pipeline` META_CEILINGS
 * / ACCEPTED_MIMES). Retained for tests + tunable frontend states; the shipped
 * page binds the REAL service. Delete once no longer referenced.
 */
import type {
  MediaCapEffective,
  MediaKind,
  OmnichannelSettings,
  OmnichannelSettingsOverrides,
  OmnichannelSettingsService,
  OmnichannelSettingsUpdate,
} from './omnichannel-settings-service';

const MB = 1024 * 1024;

const CEILINGS: Record<MediaKind, number> = {
  IMAGE: 5 * MB,
  VIDEO: 16 * MB,
  AUDIO: 16 * MB,
  VOICE: 16 * MB,
  DOCUMENT: 100 * MB,
  STICKER: 500 * 1024,
};

const MIMES: Record<MediaKind, string[]> = {
  IMAGE: ['image/jpeg', 'image/png'],
  VIDEO: ['video/3gpp', 'video/mp4'],
  AUDIO: ['audio/aac', 'audio/amr', 'audio/mp4', 'audio/mpeg', 'audio/ogg'],
  VOICE: ['audio/ogg'],
  DOCUMENT: [
    'application/pdf',
    'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'application/zip',
    'text/plain',
  ],
  STICKER: ['image/webp'],
};

/** Per-column suffix map: VOICE shares AUDIO's editable override. */
const OVERRIDE_FOR_KIND: Record<MediaKind, keyof OmnichannelSettingsOverrides> = {
  IMAGE: 'imageMaxBytes',
  VIDEO: 'videoMaxBytes',
  AUDIO: 'audioMaxBytes',
  VOICE: 'audioMaxBytes',
  DOCUMENT: 'documentMaxBytes',
  STICKER: 'stickerMaxBytes',
};

function emptyOverrides(): OmnichannelSettingsOverrides {
  return {
    imageMaxBytes: null,
    videoMaxBytes: null,
    audioMaxBytes: null,
    documentMaxBytes: null,
    stickerMaxBytes: null,
  };
}

/** Scope key: a workspace id, or the tenant default sentinel. */
const store = new Map<string, OmnichannelSettingsOverrides>();
function keyOf(workspaceId?: string | null): string {
  return workspaceId ?? '__tenant_default__';
}

function effective(overrides: OmnichannelSettingsOverrides): Record<MediaKind, MediaCapEffective> {
  const kinds: MediaKind[] = ['IMAGE', 'VIDEO', 'AUDIO', 'VOICE', 'DOCUMENT', 'STICKER'];
  const out = {} as Record<MediaKind, MediaCapEffective>;
  for (const kind of kinds) {
    const ceiling = CEILINGS[kind];
    const configured = overrides[OVERRIDE_FOR_KIND[kind]];
    out[kind] = {
      maxBytes: configured === null ? ceiling : Math.min(configured, ceiling),
      ceilingBytes: ceiling,
      acceptedMimes: MIMES[kind],
    };
  }
  return out;
}

function snapshot(workspaceId?: string | null): OmnichannelSettings {
  const overrides = store.get(keyOf(workspaceId)) ?? emptyOverrides();
  return {
    workspaceId: workspaceId ?? null,
    overrides: { ...overrides },
    effective: effective(overrides),
  };
}

export const mockOmnichannelSettingsService: OmnichannelSettingsService = {
  async get(workspaceId) {
    return snapshot(workspaceId);
  },
  async update(overrides: OmnichannelSettingsUpdate, workspaceId) {
    const current = store.get(keyOf(workspaceId)) ?? emptyOverrides();
    const next: OmnichannelSettingsOverrides = { ...current };
    (Object.keys(overrides) as (keyof OmnichannelSettingsOverrides)[]).forEach((k) => {
      const val = overrides[k];
      if (val !== undefined) next[k] = val;
    });
    store.set(keyOf(workspaceId), next);
    return snapshot(workspaceId);
  },
};

/** Test hook: reset the in-memory store between cases. */
export function __resetMockOmnichannelSettings(): void {
  store.clear();
}
