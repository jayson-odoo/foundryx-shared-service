import { beforeEach, describe, expect, it } from 'vitest';
import {
  FX_PRESETS_STORAGE_KEY,
  fxPresetFilename,
  matchFxPreset,
  parseFxPresetFile,
  readFxPresets,
  sanitizeFxPresets,
  serializeFxPreset,
  uniquePresetName,
  upsertFxPreset,
  writeFxPresets,
} from './presets';

const file = (body: unknown) => JSON.stringify(body);

describe('Foundryx UIUX presets', () => {
  beforeEach(() => window.localStorage.clear());

  it('reads a preset file, clamping and snapping numbers and dropping unknown or mistyped settings', () => {
    const parsed = parseFxPresetFile(
      file({
        type: 'foundryx-uiux-preset',
        version: 1,
        name: '  Quiet desk  ',
        settings: {
          motion: false,
          'scroll-size': 99, // clamped to 12
          'toast-time': 4.4, // snapped to 4
          scroll: true, // the default: dropped
          'hold-time': 'long', // wrong kind
          nope: 1, // unknown
        },
      }),
    );
    expect(parsed).toEqual({
      ok: true,
      name: 'Quiet desk',
      settings: { motion: false, 'scroll-size': 12, 'toast-time': 4 },
    });
  });

  it('refuses anything that is not a preset file', () => {
    for (const junk of [
      'not json',
      '[]',
      'null',
      file({ type: 'other', version: 1, settings: {} }),
      file({ type: 'foundryx-uiux-preset', version: 2, settings: {} }),
      file({ type: 'foundryx-uiux-preset', version: 1, settings: [1] }),
      file({ type: 'foundryx-uiux-preset', version: 1 }),
    ])
      expect(parseFxPresetFile(junk), junk).toEqual({ ok: false });
  });

  it('names a nameless import "Imported" and caps long names', () => {
    const nameless = parseFxPresetFile(
      file({ type: 'foundryx-uiux-preset', version: 1, settings: {} }),
    );
    expect(nameless.ok && nameless.name).toBe('Imported');
    const long = parseFxPresetFile(
      file({
        type: 'foundryx-uiux-preset',
        version: 1,
        name: 'x'.repeat(80),
        settings: {},
      }),
    );
    expect(long.ok && long.name).toHaveLength(40);
  });

  it('round-trips an export through import', () => {
    const text = serializeFxPreset('Mine', { motion: false, 'scroll-size': 8 });
    expect(JSON.parse(text)).toEqual({
      type: 'foundryx-uiux-preset',
      version: 1,
      name: 'Mine',
      settings: { motion: false, 'scroll-size': 8 },
    });
    expect(parseFxPresetFile(text)).toEqual({
      ok: true,
      name: 'Mine',
      settings: { motion: false, 'scroll-size': 8 },
    });
    expect(fxPresetFilename('Quiet desk!')).toBe(
      'foundryx-uiux-quiet-desk.json',
    );
    expect(fxPresetFilename('!!!')).toBe('foundryx-uiux-preset.json');
  });

  it('gives a clashing name " (2)", " (3)"', () => {
    const presets = [
      { name: 'Quiet', settings: {} },
      { name: 'quiet (2)', settings: {} },
    ];
    expect(uniquePresetName(presets, 'Calm')).toBe('Calm');
    expect(uniquePresetName(presets, 'Quiet')).toBe('Quiet (3)');
  });

  it('saving under an existing name updates that preset', () => {
    const first = upsertFxPreset([], 'Quiet', { motion: false });
    expect(first).toEqual({
      presets: [{ name: 'Quiet', settings: { motion: false } }],
      updated: false,
    });
    const second = upsertFxPreset(first.presets, 'QUIET', { scroll: false });
    expect(second).toEqual({
      presets: [{ name: 'Quiet', settings: { scroll: false } }],
      updated: true,
    });
  });

  it('matches the current settings to the defaults, a saved preset, or none', () => {
    const presets = [
      { name: 'Quiet', settings: { motion: false, scroll: false } },
    ];
    expect(matchFxPreset(presets, {})).toBe('');
    expect(matchFxPreset(presets, { scroll: false, motion: false })).toBe(
      'Quiet',
    );
    expect(matchFxPreset(presets, { motion: false })).toBeNull();
  });

  it('stores presets per browser and cleans what it reads back', () => {
    writeFxPresets([{ name: 'Quiet', settings: { motion: false } }]);
    expect(readFxPresets()).toEqual([
      { name: 'Quiet', settings: { motion: false } },
    ]);
    window.localStorage.setItem(
      FX_PRESETS_STORAGE_KEY,
      JSON.stringify([
        { name: 'A', settings: { 'scroll-size': 50 } },
        { name: 'a', settings: {} }, // duplicate name
        { name: '', settings: {} }, // no name
        { name: 'B' }, // no settings
        'junk',
      ]),
    );
    expect(readFxPresets()).toEqual([
      { name: 'A', settings: { 'scroll-size': 12 } },
    ]);
    window.localStorage.setItem(FX_PRESETS_STORAGE_KEY, '{broken');
    expect(readFxPresets()).toEqual([]);
    expect(sanitizeFxPresets({})).toEqual([]);
    writeFxPresets([]);
    expect(window.localStorage.getItem(FX_PRESETS_STORAGE_KEY)).toBeNull();
  });
});
