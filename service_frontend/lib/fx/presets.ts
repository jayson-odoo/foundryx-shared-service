/**
 * Foundryx UIUX Advanced settings presets (playbook 0.71.0, "Settings >
 * Presets"). Saved per browser in localStorage (`fx_presets`), each holding
 * only the settings that differ from the playbook defaults, so a later change
 * to a default reaches every preset that never touched it.
 *
 * A preset file is `{"type": "foundryx-uiux-preset", "version": 1, "name",
 * "settings"}`. Files and stored presets are untrusted: only known settings of
 * the right kind are kept, numbers clamped to their range and snapped to a
 * step (`sanitizeFxSettings`), and anything that is not a preset is refused.
 */
import { sanitizeFxSettings, type FxSettingValues } from './settings-schema';

export const FX_PRESET_TYPE = 'foundryx-uiux-preset';
export const FX_PRESET_VERSION = 1;
export const FX_PRESETS_STORAGE_KEY = 'fx_presets';
/** Larger than any real preset file; anything bigger is refused unread. */
export const FX_PRESET_MAX_BYTES = 100_000;
export const FX_PRESET_NAME_MAX = 40;

export interface FxPreset {
  name: string;
  settings: FxSettingValues;
}

export type FxPresetParse =
  | { ok: true; name: string; settings: FxSettingValues }
  | { ok: false };

const isPlainObject = (value: unknown): value is Record<string, unknown> =>
  !!value && typeof value === 'object' && !Array.isArray(value);

/** A trimmed, length-capped preset name, or '' when there is none. */
export function cleanPresetName(raw: unknown): string {
  return typeof raw === 'string' ? raw.trim().slice(0, FX_PRESET_NAME_MAX) : '';
}

/** Same settings, ignoring key order. Both sides are already sanitized. */
export function sameFxSettings(
  a: FxSettingValues,
  b: FxSettingValues,
): boolean {
  const keys = Object.keys(a);
  return (
    keys.length === Object.keys(b).length &&
    keys.every((key) => key in b && a[key] === b[key])
  );
}

/**
 * Which preset the current settings match: '' for the playbook defaults, a
 * saved preset's name, or null for "Custom (not saved)".
 */
export function matchFxPreset(
  presets: FxPreset[],
  settings: FxSettingValues,
): string | null {
  if (Object.keys(settings).length === 0) return '';
  return (
    presets.find((p) => sameFxSettings(p.settings, settings))?.name ?? null
  );
}

/** `base`, or `base (2)`, `base (3)`... when a preset already has that name. */
export function uniquePresetName(presets: FxPreset[], base: string): string {
  const taken = (name: string) =>
    presets.some((p) => p.name.toLowerCase() === name.toLowerCase());
  let name = base;
  for (let n = 2; taken(name); n += 1) name = `${base} (${n})`;
  return name;
}

/** Adds a preset, or updates the one already saved under that name. */
export function upsertFxPreset(
  presets: FxPreset[],
  name: string,
  settings: FxSettingValues,
): { presets: FxPreset[]; updated: boolean } {
  const index = presets.findIndex(
    (p) => p.name.toLowerCase() === name.toLowerCase(),
  );
  if (index < 0)
    return { presets: [...presets, { name, settings }], updated: false };
  const next = presets.slice();
  next[index] = { name: presets[index].name, settings };
  return { presets: next, updated: true };
}

/** The JSON text of a preset file. */
export function serializeFxPreset(
  name: string,
  settings: FxSettingValues,
): string {
  return JSON.stringify(
    { type: FX_PRESET_TYPE, version: FX_PRESET_VERSION, name, settings },
    null,
    2,
  );
}

/** The download name for a preset file: `foundryx-uiux-<name>.json`. */
export function fxPresetFilename(name: string): string {
  const slug = name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '');
  return `foundryx-uiux-${slug || 'preset'}.json`;
}

/** Reads a preset file's text; refuses anything that is not a preset. */
export function parseFxPresetFile(text: string): FxPresetParse {
  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch {
    return { ok: false };
  }
  if (
    !isPlainObject(data) ||
    data.type !== FX_PRESET_TYPE ||
    data.version !== FX_PRESET_VERSION ||
    !isPlainObject(data.settings)
  )
    return { ok: false };
  return {
    ok: true,
    name: cleanPresetName(data.name) || 'Imported',
    settings: sanitizeFxSettings(data.settings),
  };
}

/** Stored presets, cleaned; junk entries and duplicate names are dropped. */
export function sanitizeFxPresets(input: unknown): FxPreset[] {
  if (!Array.isArray(input)) return [];
  const out: FxPreset[] = [];
  for (const entry of input) {
    if (!isPlainObject(entry) || !isPlainObject(entry.settings)) continue;
    const name = cleanPresetName(entry.name);
    if (!name || out.some((p) => p.name.toLowerCase() === name.toLowerCase()))
      continue;
    out.push({ name, settings: sanitizeFxSettings(entry.settings) });
  }
  return out;
}

export function readFxPresets(): FxPreset[] {
  try {
    const raw = window.localStorage.getItem(FX_PRESETS_STORAGE_KEY);
    return raw ? sanitizeFxPresets(JSON.parse(raw)) : [];
  } catch {
    return [];
  }
}

export function writeFxPresets(presets: FxPreset[]): void {
  try {
    if (presets.length === 0)
      window.localStorage.removeItem(FX_PRESETS_STORAGE_KEY);
    else
      window.localStorage.setItem(
        FX_PRESETS_STORAGE_KEY,
        JSON.stringify(presets),
      );
  } catch {
    // Storage blocked: the presets still work until the page reloads.
  }
}
