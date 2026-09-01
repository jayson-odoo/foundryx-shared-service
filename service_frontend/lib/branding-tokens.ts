/**
 * Branding token whitelist + helpers (sprint-2/03).
 *
 * THE single frontend source for which theme variables a tenant may override.
 * Mirrors the Layer-1 `--foundryx-*` primitives in `css/foundryx-tokens.css`; the
 * backend keeps the canonical copy (`app/branding/token_whitelist.py`, Phase B)
 * - keep both in sync when a primitive is added.
 *
 * Deliberately EXCLUDED from the whitelist:
 *  - `-transparent` variants - derived (base color @ 0.2 alpha) so pickers stay
 *    plain colors; see `deriveTransparent`.
 *  - `--foundryx-white` / `--foundryx-black` - true constants.
 */
import type {
  BrandingTokens,
  ThemeName,
  TokenOverrides,
} from '@/types/branding';

export type TokenGroup = 'brand' | 'status' | 'grey' | 'surface';

export interface TokenDef {
  /** Stored JSON key, e.g. "primary-active". */
  key: string;
  /** CSS custom property the value lands on. */
  cssVar: string;
  label: string;
  group: TokenGroup;
}

export const TOKEN_GROUP_LABELS: Record<TokenGroup, string> = {
  brand: 'Brand',
  status: 'Status colors',
  grey: 'Grey scale',
  surface: 'Surfaces',
};

const def = (key: string, label: string, group: TokenGroup): TokenDef => ({
  key,
  cssVar: `--foundryx-${key}`,
  label,
  group,
});

/** Ordered - drives picker rows, template key order and CSS emission order. */
export const TOKEN_DEFS: TokenDef[] = [
  // Brand
  def('primary', 'Primary', 'brand'),
  def('primary-active', 'Primary · active', 'brand'),
  def('primary-accent', 'Primary · accent', 'brand'),
  def('primary-soft', 'Primary · soft', 'brand'),
  // Status
  def('success', 'Success', 'status'),
  def('success-active', 'Success · active', 'status'),
  def('success-accent', 'Success · accent', 'status'),
  def('success-soft', 'Success · soft', 'status'),
  def('danger', 'Danger', 'status'),
  def('danger-active', 'Danger · active', 'status'),
  def('danger-accent', 'Danger · accent', 'status'),
  def('danger-soft', 'Danger · soft', 'status'),
  def('info', 'Info', 'status'),
  def('info-active', 'Info · active', 'status'),
  def('info-accent', 'Info · accent', 'status'),
  def('info-soft', 'Info · soft', 'status'),
  def('warning', 'Warning', 'status'),
  def('warning-active', 'Warning · active', 'status'),
  def('warning-accent', 'Warning · accent', 'status'),
  def('warning-soft', 'Warning · soft', 'status'),
  // Greys (invert in dark - values flip per theme, names stay)
  def('grey-50', 'Grey 50', 'grey'),
  def('grey-100', 'Grey 100', 'grey'),
  def('grey-200', 'Grey 200', 'grey'),
  def('grey-300', 'Grey 300', 'grey'),
  def('grey-400', 'Grey 400', 'grey'),
  def('grey-500', 'Grey 500', 'grey'),
  def('grey-600', 'Grey 600', 'grey'),
  def('grey-700', 'Grey 700', 'grey'),
  def('grey-800', 'Grey 800', 'grey'),
  def('grey-900', 'Grey 900', 'grey'),
  def('grey-950', 'Grey 950', 'grey'),
  // Surfaces
  def('light', 'Surface · base', 'surface'),
  def('light-active', 'Surface · active', 'surface'),
  def('light-soft', 'Surface · soft', 'surface'),
  def('dark', 'Contrast · base', 'surface'),
  def('dark-active', 'Contrast · active', 'surface'),
];

export const TOKEN_KEYS = new Set(TOKEN_DEFS.map((d) => d.key));

/** Bases whose `-transparent` variant is derived from the picked color. */
const TRANSPARENT_BASES = ['primary', 'success', 'danger', 'info', 'warning'];

/** Foundryx defaults - MUST mirror `css/foundryx-tokens.css` Layer 1 exactly. */
export const FOUNDRYX_DEFAULTS: BrandingTokens = {
  light: {
    primary: '#ff5a00',
    'primary-active': '#e14b00',
    'primary-accent': '#8f3000',
    'primary-soft': '#fff2e9',
    success: '#1f9d54',
    'success-active': '#197f44',
    'success-accent': '#115c31',
    'success-soft': '#e3f5e9',
    danger: '#d93420',
    'danger-active': '#b62a1a',
    'danger-accent': '#8a1f13',
    'danger-soft': '#fce5df',
    info: '#2c7ff7',
    'info-active': '#1a63d4',
    'info-accent': '#14499c',
    'info-soft': '#e3efff',
    warning: '#e8a318',
    'warning-active': '#c2860d',
    'warning-accent': '#8f6107',
    'warning-soft': '#fcf0db',
    'grey-50': '#f7f6f4',
    'grey-100': '#ecebe7',
    'grey-200': '#d9d6cf',
    'grey-300': '#bfb8b0',
    'grey-400': '#918a80',
    'grey-500': '#6b6660',
    'grey-600': '#4b4642',
    'grey-700': '#2f2c27',
    'grey-800': '#1e1a17',
    'grey-900': '#0f0f0d',
    'grey-950': '#0a0a0a',
    light: '#ffffff',
    'light-active': '#f7f6f4',
    'light-soft': '#fbfaf8',
    dark: '#0a0a0a',
    'dark-active': '#1e1a17',
  },
  dark: {
    primary: '#ff5a00',
    'primary-active': '#ff7a1a',
    'primary-accent': '#ff9a5c',
    'primary-soft': '#2e1409',
    success: '#1f9d54',
    'success-active': '#36b86b',
    'success-accent': '#7fbf98',
    'success-soft': '#0c2613',
    danger: '#d93420',
    'danger-active': '#f0533f',
    'danger-accent': '#c98a80',
    'danger-soft': '#2e0f0a',
    info: '#2c7ff7',
    'info-active': '#5a9cf9',
    'info-accent': '#9bbde8',
    'info-soft': '#0c1b33',
    warning: '#e8a318',
    'warning-active': '#f4bc4a',
    'warning-accent': '#cbb078',
    'warning-soft': '#2a1f08',
    'grey-50': '#141210',
    'grey-100': '#141210',
    'grey-200': '#272420',
    'grey-300': '#3a3631',
    'grey-400': '#4b4642',
    'grey-500': '#6b6660',
    'grey-600': '#918a80',
    'grey-700': '#918a80',
    'grey-800': '#bfb8b0',
    'grey-900': '#d9d6cf',
    'grey-950': '#f7f6f4',
    light: '#0c0b0a',
    'light-active': '#110f0d',
    'light-soft': '#16140f',
    dark: '#f7f6f4',
    'dark-active': '#d9d6cf',
  },
};

/** #RGB, #RRGGBB or #RRGGBBAA (the formats the pickers/template accept). */
export function isValidColor(value: string): boolean {
  return /^#(?:[0-9a-f]{3}|[0-9a-f]{6}|[0-9a-f]{8})$/i.test(value.trim());
}

/** Expand #RGB → #RRGGBB so comparisons and alpha-derivation are uniform. */
export function normalizeHex(value: string): string {
  const v = value.trim().toLowerCase();
  if (/^#[0-9a-f]{3}$/.test(v)) {
    return `#${v[1]}${v[1]}${v[2]}${v[2]}${v[3]}${v[3]}`;
  }
  return v;
}

/** base color @ 0.2 alpha - the `-transparent` companion of a picked base. */
export function deriveTransparent(hex: string): string {
  const v = normalizeHex(hex);
  const r = parseInt(v.slice(1, 3), 16);
  const g = parseInt(v.slice(3, 5), 16);
  const b = parseInt(v.slice(5, 7), 16);
  return `rgba(${r}, ${g}, ${b}, 0.2)`;
}

/** Empty document - what a fresh tenant starts from. */
export function emptyTokens(): BrandingTokens {
  return { light: {}, dark: {} };
}

export function hasOverrides(tokens: BrandingTokens | null): boolean {
  return (
    !!tokens &&
    (Object.keys(tokens.light).length > 0 ||
      Object.keys(tokens.dark).length > 0)
  );
}

/** Defaults + overrides merged - the full effective palette for one theme. */
export function effectiveTokens(
  tokens: BrandingTokens | null,
  theme: ThemeName,
): TokenOverrides {
  return { ...FOUNDRYX_DEFAULTS[theme], ...(tokens?.[theme] ?? {}) };
}

/**
 * The CSS custom properties one theme's OVERRIDES produce (whitelisted vars +
 * derived `-transparent` companions). This is what the provider applies and
 * what the backend CSS endpoint will emit per block (Phase B parity).
 */
export function overrideVars(
  tokens: BrandingTokens | null,
  theme: ThemeName,
): Record<string, string> {
  const out: Record<string, string> = {};
  const overrides = tokens?.[theme] ?? {};
  for (const d of TOKEN_DEFS) {
    const v = overrides[d.key];
    if (!v) continue;
    out[d.cssVar] = normalizeHex(v);
    if (TRANSPARENT_BASES.includes(d.key)) {
      out[`${d.cssVar}-transparent`] = deriveTransparent(v);
    }
  }
  return out;
}

/** `:root { … } .dark { … }` text - preview/debug mirror of the Phase B endpoint. */
export function tokensToCss(tokens: BrandingTokens | null): string {
  const block = (selector: string, theme: ThemeName): string => {
    const vars = overrideVars(tokens, theme);
    const lines = Object.entries(vars).map(([k, v]) => `  ${k}: ${v};`);
    return lines.length ? `${selector} {\n${lines.join('\n')}\n}` : '';
  };
  return [block(':root', 'light'), block('.dark', 'dark')]
    .filter(Boolean)
    .join('\n');
}

/**
 * Downloadable template - EVERY whitelisted key prefilled with the tenant's
 * current effective value, in whitelist order. Tenants edit values (not keys)
 * and upload the file back.
 */
export function buildTemplate(tokens: BrandingTokens | null): BrandingTokens {
  const ordered = (theme: ThemeName): TokenOverrides => {
    const effective = effectiveTokens(tokens, theme);
    const out: TokenOverrides = {};
    for (const d of TOKEN_DEFS) out[d.key] = effective[d.key];
    return out;
  };
  return { light: ordered('light'), dark: ordered('dark') };
}

export interface TokenValidation {
  tokens: BrandingTokens | null;
  errors: string[];
}

/**
 * Validate an uploaded template / arbitrary JSON into a stored document.
 * Unknown keys and non-color values are reported (NOT silently dropped - the
 * tenant must see exactly why an upload was rejected). Values equal to the
 * Foundryx default are normalized away so the stored doc stays a true diff.
 */
export function validateTokens(input: unknown): TokenValidation {
  const errors: string[] = [];
  if (typeof input !== 'object' || input === null || Array.isArray(input)) {
    return {
      tokens: null,
      errors: [
        'Template must be a JSON object with "light" and "dark" sections.',
      ],
    };
  }
  const doc = input as Record<string, unknown>;
  for (const k of Object.keys(doc)) {
    if (k !== 'light' && k !== 'dark')
      errors.push(
        `Unknown top-level section "${k}" - only "light" and "dark" are allowed.`,
      );
  }
  const result = emptyTokens();
  for (const theme of ['light', 'dark'] as const) {
    const section = doc[theme];
    if (section === undefined) continue;
    if (
      typeof section !== 'object' ||
      section === null ||
      Array.isArray(section)
    ) {
      errors.push(`"${theme}" must be an object of token → color pairs.`);
      continue;
    }
    for (const [key, value] of Object.entries(
      section as Record<string, unknown>,
    )) {
      if (!TOKEN_KEYS.has(key)) {
        errors.push(`"${theme}.${key}" is not a themeable token.`);
        continue;
      }
      if (typeof value !== 'string' || !isValidColor(value)) {
        errors.push(
          `"${theme}.${key}" must be a hex color (#RGB, #RRGGBB or #RRGGBBAA).`,
        );
        continue;
      }
      const normalized = normalizeHex(value);
      // Store only true diffs - a template uploaded unchanged = no overrides.
      if (normalized !== normalizeHex(FOUNDRYX_DEFAULTS[theme][key])) {
        result[theme][key] = normalized;
      }
    }
  }
  if (errors.length) return { tokens: null, errors };
  return { tokens: hasOverrides(result) ? result : null, errors: [] };
}

/** Parse + validate a template file's text content. */
export function parseTemplateFile(text: string): TokenValidation {
  try {
    return validateTokens(JSON.parse(text));
  } catch {
    return { tokens: null, errors: ['File is not valid JSON.'] };
  }
}
