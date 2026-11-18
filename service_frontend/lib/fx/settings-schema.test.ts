import { describe, expect, it } from 'vitest';
import {
  FX_SETTING_AREAS,
  FX_SETTINGS,
  fxSetting,
  fxSettingValue,
  sanitizeFxSettings,
} from './settings-schema';

describe('Foundryx UIUX settings schema', () => {
  it('has unique keys, known areas and defaults inside their ranges', () => {
    const keys = FX_SETTINGS.map((s) => s.key);
    expect(new Set(keys).size).toBe(keys.length);
    const areas = new Set(FX_SETTING_AREAS.map((a) => a.area));
    for (const setting of FX_SETTINGS) {
      expect(areas.has(setting.area), setting.key).toBe(true);
      if (setting.dependsOn)
        expect(fxSetting(setting.dependsOn)?.kind, setting.key).toBe('switch');
      if (setting.kind === 'number') {
        expect(setting.default).toBeGreaterThanOrEqual(setting.min);
        expect(setting.default).toBeLessThanOrEqual(setting.max);
      }
    }
  });

  it('carries the playbook defaults', () => {
    expect(fxSetting('toast-time')?.default).toBe(6);
    expect(fxSetting('hold-time')?.default).toBe(3);
    expect(fxSetting('h2c-time')?.default).toBe(0.75);
    expect(fxSetting('tip-delay')?.default).toBe(0.3);
    expect(fxSetting('page-rows')?.default).toBe(50);
    expect(fxSetting('scroll-size')?.default).toBe(4);
    expect(fxSetting('safe-zone')?.default).toBe(false);
  });

  it('keeps only known, well-typed values that differ from the defaults, clamped and snapped', () => {
    expect(
      sanitizeFxSettings({
        motion: false,
        lift: true, // equals the default: dropped
        'toast-time': 99, // clamped to 15
        'scroll-size': 6.4, // snapped to 6
        'hold-time': '3', // wrong kind
        nope: true, // unknown
      }),
    ).toEqual({ motion: false, 'toast-time': 15, 'scroll-size': 6 });
    expect(sanitizeFxSettings(null)).toEqual({});
    expect(sanitizeFxSettings([1, 2])).toEqual({});
  });

  it('reads stored values, falling back to the default', () => {
    expect(fxSettingValue({ motion: false }, 'motion')).toBe(false);
    expect(fxSettingValue({}, 'motion')).toBe(true);
    expect(fxSettingValue({}, 'nope')).toBeUndefined();
  });
});
