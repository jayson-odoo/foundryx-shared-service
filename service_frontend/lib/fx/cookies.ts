/**
 * Foundryx UIUX switch and viewer theme, stored per browser in two first-party
 * cookies so the server renders the right `<html>` on first paint (no flash,
 * no inline script):
 *
 * - `fx_uiux=on` turns the switch on. Off is the cookie's absence (a deleted
 *   cookie), never `fx_uiux=off`. No cookie = off = today's UI exactly.
 * - `fx_theme=<light palette>.<dark palette>.<font>.<size>`, for example
 *   `slate.midnight.geist.90`, read only while the switch is on. Each part is
 *   validated on its own; a junk part falls back to its default.
 *
 * Mode (light, dark, auto) is not here: it stays on next-themes' own key, so
 * the user menu's Dark Mode switch and the Theme panel's Mode are one setting.
 */

export const FX_COOKIE = 'fx_uiux';
export const FX_THEME_COOKIE = 'fx_theme';

export const FX_LIGHT_PALETTES = ['slate', 'sand', 'mint'] as const;
export const FX_DARK_PALETTES = ['midnight', 'graphite', 'forest'] as const;
export const FX_FONTS = [
  'geist',
  'jakarta',
  'inter',
  'manrope',
  'dmsans',
] as const;
/** Size steps in percent; 90 is the playbook's "Normal (90%)". */
export const FX_SCALES = [75, 80, 85, 90, 100, 110, 120] as const;

export type FxLightPalette = (typeof FX_LIGHT_PALETTES)[number];
export type FxDarkPalette = (typeof FX_DARK_PALETTES)[number];
export type FxFont = (typeof FX_FONTS)[number];
export type FxScale = (typeof FX_SCALES)[number];

export interface FxTheme {
  pal: FxLightPalette;
  dpal: FxDarkPalette;
  font: FxFont;
  scale: FxScale;
}

export const FX_DEFAULT_THEME: FxTheme = {
  pal: 'slate',
  dpal: 'midnight',
  font: 'geist',
  scale: 90,
};

/** One year, as the plan's per-browser preference lifetime. */
const MAX_AGE = 60 * 60 * 24 * 365;

function pick<T extends string | number>(
  allowed: readonly T[],
  raw: string | undefined,
  fallback: T,
): T {
  if (raw === undefined) return fallback;
  const hit = allowed.find((value) => String(value) === raw);
  return hit ?? fallback;
}

export function isFxOnValue(value: string | null | undefined): boolean {
  return value === 'on';
}

export function parseFxTheme(value: string | null | undefined): FxTheme {
  const parts =
    typeof value === 'string' && value.length <= 64 ? value.split('.') : [];
  return {
    pal: pick(FX_LIGHT_PALETTES, parts[0], FX_DEFAULT_THEME.pal),
    dpal: pick(FX_DARK_PALETTES, parts[1], FX_DEFAULT_THEME.dpal),
    font: pick(FX_FONTS, parts[2], FX_DEFAULT_THEME.font),
    scale: pick(FX_SCALES, parts[3], FX_DEFAULT_THEME.scale),
  };
}

export function serializeFxTheme(theme: FxTheme): string {
  return [theme.pal, theme.dpal, theme.font, theme.scale].join('.');
}

/** A cookie's value from a `document.cookie`-style string. */
export function readCookie(
  cookieString: string,
  name: string,
): string | undefined {
  for (const part of cookieString.split(';')) {
    const at = part.indexOf('=');
    if (at === -1) continue;
    if (part.slice(0, at).trim() === name)
      return decodeURIComponent(part.slice(at + 1).trim());
  }
  return undefined;
}

/**
 * The `document.cookie` assignment that writes `name=value`, or deletes the
 * cookie when `value` is null.
 */
export function cookieAssignment(
  name: string,
  value: string | null,
  secure: boolean,
): string {
  const base =
    value === null
      ? `${name}=; Path=/; Max-Age=0; SameSite=Lax`
      : `${name}=${encodeURIComponent(value)}; Path=/; Max-Age=${MAX_AGE}; SameSite=Lax`;
  return secure ? `${base}; Secure` : base;
}

/**
 * Every Theme panel font in one stylesheet (`display=swap`); the browser
 * downloads only the face in use. Loaded only while the switch is on.
 */
export const FX_FONTS_HREF =
  'https://fonts.googleapis.com/css2?family=Geist:wght@300..700&family=Plus+Jakarta+Sans:wght@300..700&family=Inter:wght@300..700&family=Manrope:wght@300..700&family=DM+Sans:wght@300..700&display=swap';

/** Marks the font stylesheet link so it is added once and found again. */
export const FX_FONTS_LINK_ATTR = 'data-fx-fonts';

export type FxHtmlAttributes = Record<string, string | Record<string, string>>;

/**
 * The attributes the root layout puts on `<html>`. Off returns an empty
 * object, so the off markup is exactly today's.
 */
export function fxHtmlAttributes(
  on: boolean,
  theme: FxTheme,
): FxHtmlAttributes {
  if (!on) return {};
  return {
    'data-fx': 'on',
    'data-fx-pal': theme.pal,
    'data-fx-dpal': theme.dpal,
    'data-fx-font': theme.font,
    style: { '--fx-scale': String(theme.scale / 100) },
  };
}
