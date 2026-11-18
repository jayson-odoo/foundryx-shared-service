'use client';

/**
 * Foundryx UIUX switch state (playbook-uiux.md). Mounted by the root layout
 * either way; it renders no DOM of its own, so with the switch off (the
 * default, no cookie) the page is exactly today's.
 *
 * `initial` and `initialTheme` come from the server's read of the `fx_uiux`
 * and `fx_theme` cookies, so the first paint already matches. Turning the
 * switch or a theme choice changes the cookie and the `<html>` attributes at
 * once, with no reload.
 */
import {
  createContext,
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import {
  cookieAssignment,
  FX_COOKIE,
  FX_FONTS_HREF,
  FX_FONTS_LINK_ATTR,
  FX_THEME_COOKIE,
  fxHtmlAttributes,
  serializeFxTheme,
  type FxTheme,
} from '@/lib/fx/cookies';
import {
  FX_SETTINGS,
  FX_SETTINGS_STORAGE_KEY,
  fxSetting,
  fxSettingAttr,
  fxSettingVar,
  sanitizeFxSettings,
  type FxSettingValues,
} from '@/lib/fx/settings-schema';

export interface FxContextValue {
  on: boolean;
  setOn: (on: boolean) => void;
  theme: FxTheme;
  setTheme: (patch: Partial<FxTheme>) => void;
  /** Stored Advanced settings: only the values that differ from the defaults. */
  settings: FxSettingValues;
  /** Sets one Advanced setting; the default value removes it from storage. */
  setSetting: (key: string, value: boolean | number) => void;
}

export const FxContext = createContext<FxContextValue | null>(null);

const isSecure = () =>
  typeof window !== 'undefined' && window.location.protocol === 'https:';

const HTML_ATTRS = [
  'data-fx',
  'data-fx-pal',
  'data-fx-dpal',
  'data-fx-font',
] as const;

/** Writes (or removes) the switch and theme attributes on `<html>`. */
function applyHtml(on: boolean, theme: FxTheme): void {
  const html = document.documentElement;
  const attrs = fxHtmlAttributes(on, theme);
  for (const name of HTML_ATTRS) {
    const value = attrs[name];
    if (typeof value === 'string') html.setAttribute(name, value);
    else html.removeAttribute(name);
  }
  const style = attrs.style;
  if (style && typeof style === 'object')
    html.style.setProperty('--fx-scale', style['--fx-scale']);
  else html.style.removeProperty('--fx-scale');
}

/** Adds the font stylesheet once. It stays after the switch goes off: it only
 *  declares faces, and nothing uses them without the switch. */
function ensureFontLink(): void {
  if (document.querySelector(`link[${FX_FONTS_LINK_ATTR}]`)) return;
  const link = document.createElement('link');
  link.rel = 'stylesheet';
  link.href = FX_FONTS_HREF;
  link.setAttribute(FX_FONTS_LINK_ATTR, '');
  document.head.appendChild(link);
}

function unitSuffix(unit: string): string {
  return unit === 'rows' || unit === 'entries' ? '' : unit;
}

/** Reflects the stored Advanced settings onto `<html>` (playbook "Built right"). */
function applySettings(on: boolean, values: FxSettingValues): void {
  const html = document.documentElement;
  for (const setting of FX_SETTINGS) {
    const stored =
      on && setting.key in values ? values[setting.key] : undefined;
    if (setting.kind === 'switch') {
      if (stored === false)
        html.setAttribute(fxSettingAttr(setting.key), 'off');
      else html.removeAttribute(fxSettingAttr(setting.key));
    } else if (typeof stored === 'number') {
      html.style.setProperty(
        fxSettingVar(setting.key),
        `${stored}${unitSuffix(setting.unit)}`,
      );
    } else {
      html.style.removeProperty(fxSettingVar(setting.key));
    }
  }
}

function readStoredSettings(): FxSettingValues {
  try {
    const raw = window.localStorage.getItem(FX_SETTINGS_STORAGE_KEY);
    return raw ? sanitizeFxSettings(JSON.parse(raw)) : {};
  } catch {
    return {};
  }
}

function writeStoredSettings(values: FxSettingValues): void {
  try {
    if (Object.keys(values).length === 0)
      window.localStorage.removeItem(FX_SETTINGS_STORAGE_KEY);
    else
      window.localStorage.setItem(
        FX_SETTINGS_STORAGE_KEY,
        JSON.stringify(values),
      );
  } catch {
    // Storage blocked (private window, policy): the setting still applies now.
  }
}

export interface FxProviderProps {
  initial: boolean;
  initialTheme: FxTheme;
  children: ReactNode;
}

export function FxProvider({
  initial,
  initialTheme,
  children,
}: FxProviderProps) {
  const [on, setOnState] = useState(initial);
  const [theme, setThemeState] = useState<FxTheme>(initialTheme);
  const [settings, setSettings] = useState<FxSettingValues>({});

  // Settings live in this browser's storage, which the server cannot read:
  // load them after mount, and only ever apply them while the switch is on.
  useEffect(() => {
    if (initial) setSettings(readStoredSettings());
  }, [initial]);

  useEffect(() => {
    if (on) applySettings(true, settings);
  }, [on, settings]);

  const setOn = useCallback(
    (next: boolean) => {
      document.cookie = cookieAssignment(
        FX_COOKIE,
        next ? 'on' : null,
        isSecure(),
      );
      if (next) {
        ensureFontLink();
        const stored = readStoredSettings();
        setSettings(stored);
        applySettings(true, stored);
      } else {
        applySettings(false, {});
      }
      applyHtml(next, theme);
      setOnState(next);
    },
    [theme],
  );

  const setTheme = useCallback(
    (patch: Partial<FxTheme>) => {
      const next = { ...theme, ...patch };
      document.cookie = cookieAssignment(
        FX_THEME_COOKIE,
        serializeFxTheme(next),
        isSecure(),
      );
      if (on) applyHtml(true, next);
      setThemeState(next);
    },
    [on, theme],
  );

  const setSetting = useCallback((key: string, value: boolean | number) => {
    if (!fxSetting(key)) return;
    setSettings((current) => {
      const next = sanitizeFxSettings({ ...current, [key]: value });
      writeStoredSettings(next);
      return next;
    });
  }, []);

  const value = useMemo<FxContextValue>(
    () => ({ on, setOn, theme, setTheme, settings, setSetting }),
    [on, setOn, theme, setTheme, settings, setSetting],
  );

  return <FxContext.Provider value={value}>{children}</FxContext.Provider>;
}
