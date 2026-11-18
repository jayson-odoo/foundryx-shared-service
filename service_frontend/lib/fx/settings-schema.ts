/**
 * Every Foundryx UIUX Advanced setting (playbook 0.71.0, "Settings > The
 * settings"), with the playbook's own default. The Advanced settings panel
 * (slice S-ADV) renders its rows from this list; until then the provider
 * applies stored values with no UI to change them.
 *
 * How a value reaches the page (playbook "Built right"):
 * - a switch that is off sets `data-fx-<key>="off"` on `<html>` (on = absent);
 * - a number that differs from its default sets `--fx-<key>` on `<html>`.
 * Read a setting when it is used, so a change applies without a reload.
 *
 * `slice` names the build slice that adds the behaviour; the panel shows only
 * rows whose slice has merged.
 */

export type FxSettingArea =
  | 'motion'
  | 'confirm'
  | 'side-menu'
  | 'top-bar'
  | 'phones'
  | 'hold-to-copy'
  | 'tips'
  | 'quick-tool'
  | 'clipboard'
  | 'table-lists'
  | 'scrollbars'
  | 'testing';

export type FxSlice = 'F1' | 'F2' | 'F3a' | 'F3b' | 'F4' | 'F5' | 'S-QT';

interface FxSettingBase {
  key: string;
  area: FxSettingArea;
  label: string;
  note: string;
  /** Hidden while this switch is off (playbook "On/off switches"). */
  dependsOn?: string;
  slice: FxSlice;
}

export interface FxSwitchSetting extends FxSettingBase {
  kind: 'switch';
  default: boolean;
}

export interface FxNumberSetting extends FxSettingBase {
  kind: 'number';
  default: number;
  min: number;
  max: number;
  step: number;
  unit: 's' | 'px' | '%' | 'rows' | 'entries';
}

export type FxSetting = FxSwitchSetting | FxNumberSetting;

export const FX_SETTING_AREAS: { area: FxSettingArea; label: string }[] = [
  { area: 'motion', label: 'Motion' },
  { area: 'confirm', label: 'Confirm dialogs' },
  { area: 'side-menu', label: 'Side menu' },
  { area: 'top-bar', label: 'Top bar' },
  { area: 'phones', label: 'Phones' },
  { area: 'hold-to-copy', label: 'Hold to Copy' },
  { area: 'tips', label: 'Tips by the pointer' },
  { area: 'quick-tool', label: 'Quick Tool and RCT' },
  { area: 'clipboard', label: 'Clipboard' },
  { area: 'table-lists', label: 'Table lists' },
  { area: 'scrollbars', label: 'Scrollbars' },
  { area: 'testing', label: 'Testing' },
];

const sw = (
  area: FxSettingArea,
  slice: FxSlice,
  key: string,
  label: string,
  note: string,
  def: boolean,
  dependsOn?: string,
): FxSwitchSetting => ({
  kind: 'switch',
  area,
  slice,
  key,
  label,
  note,
  default: def,
  dependsOn,
});

const num = (
  area: FxSettingArea,
  slice: FxSlice,
  key: string,
  label: string,
  note: string,
  def: number,
  range: {
    min: number;
    max: number;
    step: number;
    unit: FxNumberSetting['unit'];
  },
  dependsOn?: string,
): FxNumberSetting => ({
  kind: 'number',
  area,
  slice,
  key,
  label,
  note,
  default: def,
  ...range,
  dependsOn,
});

export const FX_SETTINGS: FxSetting[] = [
  // Motion
  sw(
    'motion',
    'F1',
    'motion',
    'Animations',
    'Things slide and fade instead of jumping.',
    true,
  ),
  sw(
    'motion',
    'F1',
    'theme-fade',
    'Cross-fade on theme changes',
    'The page fades when the mode or palette changes.',
    true,
    'motion',
  ),
  sw(
    'motion',
    'F2',
    'lift',
    'Hover lift',
    'Clickable items rise slightly under the mouse.',
    true,
    'motion',
  ),
  sw(
    'motion',
    'F2',
    'lean',
    "The red action's lean",
    'The red action leans toward the pointer.',
    true,
    'motion',
  ),
  num(
    'motion',
    'F2',
    'toast-time',
    'How long toasts stay',
    'Time before a done message closes.',
    6,
    { min: 3, max: 15, step: 1, unit: 's' },
  ),
  sw(
    'motion',
    'F3b',
    'shimmer',
    'Shimmer on loading placeholders',
    'Placeholders shimmer while content loads.',
    true,
    'motion',
  ),
  // Confirm dialogs
  sw(
    'confirm',
    'F2',
    'hold',
    'Press and hold to confirm',
    'Risky actions need a press and hold.',
    true,
  ),
  num(
    'confirm',
    'F2',
    'hold-time',
    'Hold time',
    'How long to hold.',
    3,
    { min: 1, max: 5, step: 0.5, unit: 's' },
    'hold',
  ),
  // Side menu
  num(
    'side-menu',
    'F5',
    'rail-wait',
    'Wait before it folds to icons',
    'Time after the pointer leaves.',
    0.3,
    { min: 0, max: 2, step: 0.1, unit: 's' },
  ),
  // Top bar
  sw(
    'top-bar',
    'F5',
    'merge',
    'Merge into the page header on scroll',
    'Wider screens only.',
    true,
  ),
  // Phones
  sw(
    'phones',
    'F5',
    'condense',
    'Condense the top bar on scroll',
    'The top bar shrinks as the page scrolls.',
    true,
  ),
  sw(
    'phones',
    'F5',
    'float-act',
    'Floating red action',
    'The red action floats once the header scrolls away.',
    true,
  ),
  // Hold to Copy
  sw(
    'hold-to-copy',
    'F3b',
    'h2c',
    'Hold to Copy',
    'Press and hold a value to copy it.',
    true,
  ),
  num(
    'hold-to-copy',
    'F3b',
    'h2c-time',
    'Hold time',
    'The ring fills in this time.',
    0.75,
    { min: 0.25, max: 2, step: 0.25, unit: 's' },
    'h2c',
  ),
  num(
    'hold-to-copy',
    'F3b',
    'h2c-reach',
    'Reach around the text',
    'How far outside the text a hold still counts.',
    8,
    { min: 0, max: 24, step: 2, unit: 'px' },
    'h2c',
  ),
  num(
    'hold-to-copy',
    'F3b',
    'h2c-copied',
    'How long "Copied" shows',
    'Time the confirmation stays.',
    1.4,
    { min: 0.5, max: 4, step: 0.1, unit: 's' },
    'h2c',
  ),
  // Tips by the pointer
  sw(
    'tips',
    'F2',
    'tips',
    'Styled tooltips',
    'Themed tooltips that follow the pointer.',
    true,
  ),
  sw(
    'tips',
    'F2',
    'touch-tips',
    'Press and hold for tips on touch',
    'A long press shows the tip on touch screens.',
    true,
    'tips',
  ),
  num(
    'tips',
    'F2',
    'tip-delay',
    'Tooltip delay',
    'Wait before a tooltip shows.',
    0.3,
    { min: 0, max: 1.5, step: 0.1, unit: 's' },
    'tips',
  ),
  num(
    'tips',
    'F2',
    'tip-fade',
    'Tooltip fade-in',
    'How long a tooltip takes to appear.',
    0.15,
    { min: 0, max: 0.5, step: 0.05, unit: 's' },
    'tips',
  ),
  num(
    'tips',
    'F2',
    'tip-bg',
    'Tooltip background',
    'How solid the tooltip backing is.',
    92,
    { min: 50, max: 100, step: 2, unit: '%' },
    'tips',
  ),
  num(
    'tips',
    'S-QT',
    'tool-bg',
    'Tool Background strength',
    'Backing of the copy icon and the Quick Tool.',
    25,
    { min: 0, max: 100, step: 5, unit: '%' },
  ),
  num(
    'tips',
    'S-QT',
    'tool-blur',
    'Tool Background blur',
    'Blur behind the copy icon and the Quick Tool.',
    0.75,
    { min: 0, max: 4, step: 0.25, unit: 'px' },
  ),
  num(
    'tips',
    'S-QT',
    'tool-ink',
    'Icon and text strength',
    'Strength of tool icons and text.',
    50,
    { min: 20, max: 100, step: 5, unit: '%' },
  ),
  // Quick Tool and RCT
  sw(
    'quick-tool',
    'S-QT',
    'qt',
    'Quick Tool and RCT',
    'The floating tool and the right-click tool.',
    true,
  ),
  num(
    'quick-tool',
    'S-QT',
    'rct-hold',
    'RCT hold time',
    'Press and hold time on touch.',
    0.75,
    { min: 0.25, max: 2, step: 0.25, unit: 's' },
    'qt',
  ),
  sw(
    'quick-tool',
    'S-QT',
    'qt-hover',
    'Widget opens on hover',
    'The widget opens when the pointer reaches it.',
    true,
    'qt',
  ),
  num(
    'quick-tool',
    'S-QT',
    'qt-close',
    'Wait before closing',
    'Time after the pointer leaves.',
    0.3,
    { min: 0, max: 2, step: 0.1, unit: 's' },
    'qt',
  ),
  sw(
    'quick-tool',
    'S-QT',
    'qt-clipboard',
    'Clipboard',
    'Show the Clipboard tool.',
    true,
    'qt',
  ),
  sw(
    'quick-tool',
    'S-QT',
    'qt-ai',
    'Ask AI',
    'Show the Ask AI tool.',
    true,
    'qt',
  ),
  sw(
    'quick-tool',
    'S-QT',
    'qt-shot',
    'Screenshot',
    'Show the Screenshot tool.',
    true,
    'qt',
  ),
  sw(
    'quick-tool',
    'S-QT',
    'qt-issue',
    'Report Issue',
    'Show the Report Issue tool.',
    true,
    'qt',
  ),
  // Clipboard
  sw(
    'clipboard',
    'S-QT',
    'clip',
    'Clipboard',
    'Keep recent copies at hand.',
    true,
  ),
  num(
    'clipboard',
    'S-QT',
    'clip-keep',
    'Entries kept',
    'How many copies the Clipboard keeps.',
    10,
    { min: 3, max: 30, step: 1, unit: 'entries' },
    'clip',
  ),
  sw(
    'clipboard',
    'S-QT',
    'clip-manual',
    'Keeps manual copies',
    'Copies made with the keyboard land here too.',
    true,
    'clip',
  ),
  sw(
    'clipboard',
    'S-QT',
    'clip-keys',
    'Number keys and keycaps',
    'Number keys paste an entry.',
    true,
    'clip',
  ),
  sw(
    'clipboard',
    'S-QT',
    'clip-dots',
    'Source dots',
    'A dot shows where each copy came from.',
    true,
    'clip',
  ),
  // Table lists
  sw(
    'table-lists',
    'F3a',
    'views',
    'Smart view and Table view',
    'Off: a table that does not fit turns into cards.',
    true,
  ),
  sw(
    'table-lists',
    'F3a',
    'columns',
    'Choose and order columns',
    'The Columns panel.',
    true,
  ),
  sw(
    'table-lists',
    'F3a',
    'col-drag',
    'Drag headers to move columns',
    'Move a column by dragging its header.',
    true,
    'columns',
  ),
  sw(
    'table-lists',
    'F3a',
    'header-search',
    'Search and filter from a header',
    'Each header can search or filter its column.',
    true,
  ),
  sw(
    'table-lists',
    'F3a',
    'freeze',
    'Freeze the header row',
    'The header row stays under the page header.',
    true,
  ),
  sw(
    'table-lists',
    'F3a',
    'header-sort',
    'Sort from a header',
    'Click a header to sort by it.',
    true,
  ),
  num(
    'table-lists',
    'F3a',
    'page-rows',
    'Rows per page on long lists',
    'Rows a long list shows at once.',
    50,
    { min: 25, max: 100, step: 25, unit: 'rows' },
  ),
  // Scrollbars
  sw(
    'scrollbars',
    'F1',
    'scroll',
    'Slim scrollbars',
    'Thin scrollbars that match the theme.',
    true,
  ),
  num(
    'scrollbars',
    'F1',
    'scroll-size',
    'Thickness',
    'Width of the slim scrollbars.',
    4,
    { min: 2, max: 12, step: 1, unit: 'px' },
    'scroll',
  ),
  // Testing
  sw(
    'testing',
    'F5',
    'safe-zone',
    'Show the submenu safe zone',
    'Draws the area a submenu keeps open.',
    false,
  ),
];

/** Stored values: only what differs from the playbook defaults. */
export type FxSettingValues = Record<string, boolean | number>;

export function fxSetting(key: string): FxSetting | undefined {
  return FX_SETTINGS.find((setting) => setting.key === key);
}

/** Snaps a number to its setting's step and clamps it to its range. */
export function clampFxNumber(setting: FxNumberSetting, value: number): number {
  const steps = Math.round((value - setting.min) / setting.step);
  const snapped = setting.min + steps * setting.step;
  const clamped = Math.min(setting.max, Math.max(setting.min, snapped));
  return Number(clamped.toFixed(4));
}

/**
 * Keeps only known settings of the right kind that differ from their
 * defaults, numbers clamped and snapped (stored data is untrusted).
 */
export function sanitizeFxSettings(input: unknown): FxSettingValues {
  const out: FxSettingValues = {};
  if (!input || typeof input !== 'object' || Array.isArray(input)) return out;
  for (const [key, raw] of Object.entries(input as Record<string, unknown>)) {
    const setting = fxSetting(key);
    if (!setting) continue;
    if (
      setting.kind === 'switch' &&
      typeof raw === 'boolean' &&
      raw !== setting.default
    ) {
      out[key] = raw;
    } else if (
      setting.kind === 'number' &&
      typeof raw === 'number' &&
      Number.isFinite(raw)
    ) {
      const value = clampFxNumber(setting, raw);
      if (value !== setting.default) out[key] = value;
    }
  }
  return out;
}

/** The effective value of a setting: the stored one, else the default. */
export function fxSettingValue(
  values: FxSettingValues,
  key: string,
): boolean | number | undefined {
  const setting = fxSetting(key);
  if (!setting) return undefined;
  return key in values ? values[key] : setting.default;
}

/** The CSS custom property a number setting sets on `<html>`. */
export function fxSettingVar(key: string): string {
  return `--fx-${key}`;
}

/** The attribute a switch setting sets on `<html>` while it is off. */
export function fxSettingAttr(key: string): string {
  return `data-fx-${key}`;
}

/** The localStorage key holding the stored values. */
export const FX_SETTINGS_STORAGE_KEY = 'fx_settings';
