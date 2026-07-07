/**
 * A small, BUNDLED emoji set for the composer picker (plan 12 AC-12-08).
 *
 * Deliberately in-repo (no npm/CDN emoji package) — the media/asset CSP forbids
 * loading a picker's sprite sheet or data file from an external origin. A curated
 * common set is enough for a chat composer; a full picker is a later enhancement.
 */
export interface EmojiGroup {
  label: string;
  emojis: string[];
}

export const EMOJI_GROUPS: EmojiGroup[] = [
  {
    label: 'Smileys',
    emojis: [
      '😀', '😃', '😄', '😁', '😆', '😅', '😂', '🙂', '🙃', '😉',
      '😊', '😇', '🥰', '😍', '😘', '😋', '😜', '🤪', '🤗', '🤔',
      '🤭', '🤫', '😐', '😑', '😶', '🙄', '😏', '😴', '😪', '😌',
      '😬', '🥲', '😢', '😭', '😤', '😠', '😡', '🥳', '😎', '🤩',
    ],
  },
  {
    label: 'Gestures',
    emojis: [
      '👍', '👎', '👌', '✌️', '🤞', '🤟', '🤙', '👋', '🙏', '👏',
      '🙌', '💪', '🤝', '👊', '✊', '☝️', '👉', '👈', '🫶', '🤲',
    ],
  },
  {
    label: 'Hearts',
    emojis: [
      '❤️', '🧡', '💛', '💚', '💙', '💜', '🖤', '🤍', '💔', '❣️',
      '💕', '💞', '💓', '💗', '💖', '💘', '💝', '✨', '🔥', '⭐',
    ],
  },
  {
    label: 'Objects',
    emojis: [
      '✅', '❌', '⚠️', '📌', '📎', '📅', '⏰', '📞', '📧', '💬',
      '🎉', '🎊', '🎁', '💯', '🚀', '💡', '📷', '🎵', '☕', '🍕',
    ],
  },
];
