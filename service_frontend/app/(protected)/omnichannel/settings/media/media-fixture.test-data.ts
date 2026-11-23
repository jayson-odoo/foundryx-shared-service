/** Test data for the media limits page tests (parity and the new look). */
import type { OmnichannelSettings } from '@/services/omnichannel-settings-service';

const MB = 1024 * 1024;

export const MEDIA_SETTINGS_FIXTURE: OmnichannelSettings = {
  workspaceId: null,
  overrides: {
    imageMaxBytes: 2 * MB,
    videoMaxBytes: null,
    audioMaxBytes: null,
    documentMaxBytes: 50 * MB,
    stickerMaxBytes: null,
  },
  effective: {
    IMAGE: { maxBytes: 2 * MB, ceilingBytes: 5 * MB, acceptedMimes: ['image/jpeg', 'image/png'] },
    VIDEO: { maxBytes: 16 * MB, ceilingBytes: 16 * MB, acceptedMimes: ['video/mp4', 'video/3gpp'] },
    AUDIO: { maxBytes: 16 * MB, ceilingBytes: 16 * MB, acceptedMimes: ['audio/ogg', 'audio/mpeg'] },
    VOICE: { maxBytes: 16 * MB, ceilingBytes: 16 * MB, acceptedMimes: ['audio/ogg'] },
    DOCUMENT: {
      maxBytes: 50 * MB,
      ceilingBytes: 100 * MB,
      acceptedMimes: [
        'application/pdf',
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'text/plain',
      ],
    },
    STICKER: { maxBytes: 0.5 * MB, ceilingBytes: 0.5 * MB, acceptedMimes: ['image/webp'] },
  },
};
