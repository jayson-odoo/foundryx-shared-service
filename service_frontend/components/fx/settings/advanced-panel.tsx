'use client';

/**
 * The Advanced settings panel (playbook 0.71.0, "Settings > Advanced
 * settings" and "Presets"), opened from the Theme panel's "Advanced settings"
 * link while the Foundryx UIUX switch is on.
 *
 * A floating, see-through panel that leaves the page under it usable: it
 * opens at the top right, drags by its header (or the grip's arrow keys, Shift
 * for bigger steps), may hang off the bottom but never off the sides or top,
 * and remembers its place per browser. Inside: the master switch, the preset
 * bar, "Find a setting", one section per area with its own Reset, and Reset
 * all. Rows come from `lib/fx/settings-schema.ts`, and only rows whose
 * behaviour exists in this build are shown (`fxSettingBuilt`).
 *
 * Values are stored per browser (`fx_settings`, only what differs from the
 * defaults) through the switch provider; presets in `fx_presets`.
 *
 * Renders nothing while closed, outside the switch provider and inside
 * `<FxOff>`, so it never changes a page with the switch off.
 */
import {
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
  type PointerEvent as ReactPointerEvent,
} from 'react';
import { FileDown, FileUp, GripVertical, Save, Search, X } from 'lucide-react';
import { createPortal } from 'react-dom';
import {
  cleanPresetName,
  FX_PRESET_MAX_BYTES,
  fxPresetFilename,
  matchFxPreset,
  parseFxPresetFile,
  readFxPresets,
  serializeFxPreset,
  uniquePresetName,
  upsertFxPreset,
  writeFxPresets,
  type FxPreset,
} from '@/lib/fx/presets';
import {
  FX_SETTING_AREAS,
  FX_SETTINGS,
  fxSettingBuilt,
  fxSettingValue,
  type FxNumberSetting,
  type FxSetting,
  type FxSettingValues,
} from '@/lib/fx/settings-schema';
import { toast } from '@/lib/toast';
import { cn } from '@/lib/utils';
import { useFxControls } from '@/hooks/use-fx';
import type { FxContextValue } from '@/providers/fx-provider';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { PRESSED_CLASS } from '@/components/ui/primitive-classes';
import { Slider, SliderThumb } from '@/components/ui/slider';
import { Switch } from '@/components/ui/switch';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { MasterSwitch } from '@/components/fx/theme/theme-panel';
import { SearchSelect } from '@/components/platform/search-select';
import { closeFxAdvanced, useFxAdvancedOpen } from './advanced-open';

/** Where the panel's place is remembered (per browser). */
export const FX_ADVANCED_POS_KEY = 'fx_adv_pos';
const EDGE = 16;
const KEY_STEP = 10;
const KEY_STEP_BIG = 50;
const DEFAULTS_VALUE = 'defaults';
const PRESET_PREFIX = 'preset:';

/** The value text of a number setting: "1 s", "8 px", "92%", "50 rows". */
export function formatFxValue(setting: FxNumberSetting, value: number): string {
  const shown = Number(value.toFixed(2));
  return setting.unit === '%' ? `${shown}%` : `${shown} ${setting.unit}`;
}

/** Rows the panel shows now: built, not hidden by an off switch, matching the
 *  find text (name, note or section). */
export function visibleFxRows(
  values: FxSettingValues,
  query: string,
): FxSetting[] {
  const q = query.trim().toLowerCase();
  return FX_SETTINGS.filter((setting) => {
    if (!fxSettingBuilt(setting)) return false;
    if (
      setting.dependsOn &&
      fxSettingValue(values, setting.dependsOn) === false
    )
      return false;
    if (!q) return true;
    const area =
      FX_SETTING_AREAS.find((a) => a.area === setting.area)?.label ?? '';
    return `${area} ${setting.label} ${setting.note}`.toLowerCase().includes(q);
  });
}

/** Sets every setting to `values` (missing = the playbook default). */
function applyFxValues(fx: FxContextValue, values: FxSettingValues): void {
  for (const setting of FX_SETTINGS)
    fx.setSetting(
      setting.key,
      setting.key in values ? values[setting.key] : setting.default,
    );
}

interface Pos {
  x: number;
  y: number;
}

function readPos(): Pos | null {
  try {
    const raw = window.localStorage.getItem(FX_ADVANCED_POS_KEY);
    const data: unknown = raw ? JSON.parse(raw) : null;
    if (
      data &&
      typeof data === 'object' &&
      Number.isFinite((data as Pos).x) &&
      Number.isFinite((data as Pos).y)
    )
      return { x: (data as Pos).x, y: (data as Pos).y };
  } catch {
    // Unreadable: open at the default place.
  }
  return null;
}

function writePos(pos: Pos): void {
  try {
    window.localStorage.setItem(FX_ADVANCED_POS_KEY, JSON.stringify(pos));
  } catch {
    // Storage blocked: the place is kept until the page reloads.
  }
}

/** Never off the sides or the top; off the bottom only down to the header. */
function clampPos(pos: Pos, panel: HTMLElement, header: HTMLElement): Pos {
  const maxX = Math.max(0, window.innerWidth - panel.offsetWidth);
  const maxY = Math.max(0, window.innerHeight - header.offsetHeight);
  return {
    x: Math.round(Math.min(maxX, Math.max(0, pos.x))),
    y: Math.round(Math.min(maxY, Math.max(0, pos.y))),
  };
}

const SECTION_LABEL =
  'text-xs font-semibold uppercase tracking-wide text-(--fx-ink-3)';
const LINK_BUTTON =
  'rounded-(--fx-r-s) text-xs font-semibold text-(--fx-link) hover:underline';

function IconAction({
  label,
  onClick,
  children,
}: {
  label: string;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          mode="icon"
          size="sm"
          aria-label={label}
          onClick={onClick}
        >
          {children}
        </Button>
      </TooltipTrigger>
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  );
}

function SwitchRow({
  setting,
  value,
  onChange,
}: {
  setting: FxSetting;
  value: boolean;
  onChange: (value: boolean) => void;
}) {
  const id = useId();
  const changed = value !== setting.default;
  return (
    <div className="flex items-center justify-between gap-3 py-1.5">
      <div className="min-w-0">
        <label
          htmlFor={id}
          className={cn(
            'block text-sm font-medium',
            changed && 'text-(--fx-link)',
          )}
        >
          {setting.label}
        </label>
        <p className="text-xs text-(--fx-ink-3)">{setting.note}</p>
      </div>
      <Switch id={id} checked={value} onCheckedChange={onChange} />
    </div>
  );
}

function NumberRow({
  setting,
  value,
  onChange,
}: {
  setting: FxNumberSetting;
  value: number;
  onChange: (value: number) => void;
}) {
  const labelId = useId();
  const [draft, setDraft] = useState<number | null>(null);
  const shown = draft ?? value;
  const changed = shown !== setting.default;
  return (
    <div className="flex flex-col gap-1.5 py-1.5">
      <div className="flex items-baseline justify-between gap-3">
        <span
          id={labelId}
          className={cn('text-sm font-medium', changed && 'text-(--fx-link)')}
        >
          {setting.label}
        </span>
        <span
          className={cn(
            'shrink-0 text-xs tabular-nums text-(--fx-ink-2)',
            changed && 'text-(--fx-link)',
          )}
        >
          {formatFxValue(setting, shown)}
        </span>
      </div>
      <p className="text-xs text-(--fx-ink-3)">{setting.note}</p>
      <Slider
        min={setting.min}
        max={setting.max}
        step={setting.step}
        value={[shown]}
        onValueChange={([next]) => setDraft(next)}
        onValueCommit={([next]) => {
          setDraft(null);
          onChange(next);
        }}
        aria-labelledby={labelId}
      >
        <SliderThumb
          aria-labelledby={labelId}
          aria-valuetext={formatFxValue(setting, shown)}
        />
      </Slider>
    </div>
  );
}

function PresetBar({ fx }: { fx: FxContextValue }) {
  const [presets, setPresetsState] = useState<FxPreset[]>(readFxPresets);
  const [saving, setSaving] = useState(false);
  const [name, setName] = useState('');
  const [nameError, setNameError] = useState('');
  const [fileError, setFileError] = useState('');
  const fileRef = useRef<HTMLInputElement>(null);
  const nameId = useId();

  const setPresets = useCallback((next: FxPreset[]) => {
    writeFxPresets(next);
    setPresetsState(next);
  }, []);

  const current = matchFxPreset(presets, fx.settings);
  const options = [
    { value: DEFAULTS_VALUE, label: 'Playbook defaults' },
    ...presets.map((p) => ({ value: PRESET_PREFIX + p.name, label: p.name })),
  ];
  const selectValue =
    current === null
      ? null
      : current === ''
        ? DEFAULTS_VALUE
        : PRESET_PREFIX + current;

  const pick = (value: string) => {
    if (value === DEFAULTS_VALUE) {
      applyFxValues(fx, {});
      return;
    }
    const preset = presets.find((p) => PRESET_PREFIX + p.name === value);
    if (preset) applyFxValues(fx, preset.settings);
  };

  const openSave = () => {
    setName(current ? current : '');
    setNameError('');
    setSaving(true);
  };

  const save = (event: FormEvent) => {
    event.preventDefault();
    const clean = cleanPresetName(name);
    if (!clean) {
      setNameError('Give it a name.');
      return;
    }
    const { presets: next, updated } = upsertFxPreset(
      presets,
      clean,
      fx.settings,
    );
    setPresets(next);
    setSaving(false);
    toast.success(
      updated ? `Updated preset "${clean}"` : `Saved preset "${clean}"`,
    );
  };

  const exportPreset = () => {
    const label =
      current === ''
        ? 'Playbook defaults'
        : current === null
          ? 'Custom'
          : current;
    const blob = new Blob([serializeFxPreset(label, fx.settings)], {
      type: 'application/json',
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = fxPresetFilename(label);
    document.body.append(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    toast.success(`Exported "${label}"`);
  };

  const importFile = async (file: File | undefined) => {
    setFileError('');
    if (!file) return;
    if (file.size > FX_PRESET_MAX_BYTES) {
      setFileError('That file is too big to be a preset.');
      return;
    }
    let text: string;
    try {
      text = await file.text();
    } catch {
      setFileError("The file couldn't be read.");
      return;
    }
    const parsed = parseFxPresetFile(text);
    if (!parsed.ok) {
      setFileError("That file isn't a preset.");
      return;
    }
    const finalName = uniquePresetName(presets, parsed.name);
    setPresets([...presets, { name: finalName, settings: parsed.settings }]);
    applyFxValues(fx, parsed.settings);
    toast.success(`Imported "${finalName}"`);
  };

  const remove = () => {
    if (!current) return;
    const index = presets.findIndex((p) => p.name === current);
    if (index < 0) return;
    const gone = presets[index];
    const next = presets.filter((_, i) => i !== index);
    setPresets(next);
    toast.success(`Deleted preset "${gone.name}"`, {
      action: {
        label: 'Undo',
        onClick: () => {
          setPresetsState((now) => {
            if (
              now.some((p) => p.name.toLowerCase() === gone.name.toLowerCase())
            )
              return now;
            const restored = now.slice();
            restored.splice(Math.min(index, restored.length), 0, gone);
            writeFxPresets(restored);
            return restored;
          });
        },
      },
    });
  };

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-1">
        <SearchSelect
          ariaLabel="Preset"
          options={options}
          value={selectValue}
          onChange={pick}
          placeholder="Custom (not saved)"
          searchPlaceholder="Find a preset"
          className="min-w-0 flex-1"
        />
        <IconAction label="Save preset" onClick={openSave}>
          <Save />
        </IconAction>
        <IconAction label="Export preset" onClick={exportPreset}>
          <FileDown />
        </IconAction>
        <IconAction
          label="Import preset"
          onClick={() => fileRef.current?.click()}
        >
          <FileUp />
        </IconAction>
        <input
          ref={fileRef}
          type="file"
          accept=".json,application/json"
          hidden
          aria-label="Preset file"
          data-testid="fx-preset-file"
          onChange={(event) => {
            const file = event.target.files?.[0];
            event.target.value = '';
            void importFile(file);
          }}
        />
      </div>
      {current ? (
        <button
          type="button"
          onClick={remove}
          className={cn(PRESSED_CLASS, LINK_BUTTON, 'self-start')}
        >
          {`Delete "${current}"`}
        </button>
      ) : null}
      {fileError ? (
        <p role="alert" className="text-xs text-destructive">
          {fileError}
        </p>
      ) : null}
      {saving ? (
        <form onSubmit={save} className="flex flex-col gap-1.5" noValidate>
          <label htmlFor={nameId} className="text-xs font-medium">
            Preset name
          </label>
          <div className="flex items-center gap-2">
            <Input
              id={nameId}
              autoFocus
              autoComplete="off"
              maxLength={40}
              value={name}
              onChange={(event) => {
                setName(event.target.value);
                setNameError('');
              }}
              aria-invalid={nameError ? true : undefined}
              className="min-w-0 flex-1"
            />
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => setSaving(false)}
            >
              Cancel
            </Button>
            <Button type="submit" size="sm">
              Save preset
            </Button>
          </div>
          {nameError ? (
            <p role="alert" className="text-xs text-destructive">
              {nameError}
            </p>
          ) : null}
        </form>
      ) : null}
    </div>
  );
}

function Settings({ fx }: { fx: FxContextValue }) {
  const [query, setQuery] = useState('');
  const rows = visibleFxRows(fx.settings, query);
  const sections = FX_SETTING_AREAS.map((area) => ({
    ...area,
    rows: rows.filter((row) => row.area === area.area),
  })).filter((section) => section.rows.length > 0);

  const resetArea = (area: string) => {
    for (const setting of FX_SETTINGS)
      if (setting.area === area && fxSettingBuilt(setting))
        fx.setSetting(setting.key, setting.default);
  };

  return (
    <>
      <label className="relative block">
        <span className="sr-only">Find a setting</span>
        <Search
          aria-hidden="true"
          className="pointer-events-none absolute start-2.5 top-1/2 size-4 -translate-y-1/2 text-(--fx-ink-3)"
        />
        <Input
          type="search"
          placeholder="Find a setting"
          autoComplete="off"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          className="ps-8"
        />
      </label>
      <div className="flex flex-col gap-4">
        {sections.map((section) => (
          <section
            key={section.area}
            aria-label={section.label}
            className="flex flex-col"
          >
            <div className="flex items-center justify-between">
              <h3 className={SECTION_LABEL}>{section.label}</h3>
              <button
                type="button"
                aria-label={`Reset ${section.label}`}
                onClick={() => resetArea(section.area)}
                className={cn(PRESSED_CLASS, LINK_BUTTON)}
              >
                Reset
              </button>
            </div>
            {section.rows.map((setting) =>
              setting.kind === 'switch' ? (
                <SwitchRow
                  key={setting.key}
                  setting={setting}
                  value={fxSettingValue(fx.settings, setting.key) as boolean}
                  onChange={(value) => fx.setSetting(setting.key, value)}
                />
              ) : (
                <NumberRow
                  key={setting.key}
                  setting={setting}
                  value={fxSettingValue(fx.settings, setting.key) as number}
                  onChange={(value) => fx.setSetting(setting.key, value)}
                />
              ),
            )}
          </section>
        ))}
        {sections.length === 0 ? (
          <p className="py-4 text-center text-sm text-(--fx-ink-3)">
            No setting matches.
          </p>
        ) : null}
      </div>
    </>
  );
}

function Panel({ fx }: { fx: FxContextValue }) {
  const panelRef = useRef<HTMLDivElement>(null);
  const headerRef = useRef<HTMLDivElement>(null);
  const drag = useRef<{ dx: number; dy: number; id: number } | null>(null);
  const [pos, setPos] = useState<Pos | null>(null);
  const titleId = useId();

  const place = useCallback((next: Pos, remember: boolean) => {
    const panel = panelRef.current;
    const header = headerRef.current;
    if (!panel || !header) return;
    const clamped = clampPos(next, panel, header);
    setPos(clamped);
    if (remember) writePos(clamped);
  }, []);

  // First place: the remembered one, else the top right.
  useLayoutEffect(() => {
    const panel = panelRef.current;
    if (!panel) return;
    place(
      readPos() ?? {
        x: window.innerWidth - panel.offsetWidth - EDGE,
        y: EDGE,
      },
      false,
    );
    panel.focus();
  }, [place]);

  useEffect(() => {
    const onResize = () => setPos((now) => (now ? { ...now } : now));
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);

  // Keep it inside the window after a resize.
  useEffect(() => {
    const panel = panelRef.current;
    const header = headerRef.current;
    if (!pos || !panel || !header) return;
    const clamped = clampPos(pos, panel, header);
    if (clamped.x !== pos.x || clamped.y !== pos.y) setPos(clamped);
  }, [pos]);

  const onPointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.button !== 0 || !pos) return;
    if ((event.target as HTMLElement).closest('button:not([data-fx-grip])'))
      return;
    drag.current = {
      dx: event.clientX - pos.x,
      dy: event.clientY - pos.y,
      id: event.pointerId,
    };
    event.currentTarget.setPointerCapture?.(event.pointerId);
  };
  const onPointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    const d = drag.current;
    if (!d || d.id !== event.pointerId) return;
    place({ x: event.clientX - d.dx, y: event.clientY - d.dy }, false);
  };
  const onPointerUp = (event: ReactPointerEvent<HTMLDivElement>) => {
    const d = drag.current;
    if (!d || d.id !== event.pointerId) return;
    drag.current = null;
    place({ x: event.clientX - d.dx, y: event.clientY - d.dy }, true);
  };

  const onGripKey = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (!pos) return;
    const step = event.shiftKey ? KEY_STEP_BIG : KEY_STEP;
    const moves: Record<string, Pos> = {
      ArrowLeft: { x: pos.x - step, y: pos.y },
      ArrowRight: { x: pos.x + step, y: pos.y },
      ArrowUp: { x: pos.x, y: pos.y - step },
      ArrowDown: { x: pos.x, y: pos.y + step },
    };
    const next = moves[event.key];
    if (!next) return;
    event.preventDefault();
    place(next, true);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    // Esc inside a menu opened from the panel (rendered elsewhere) closes
    // only that menu.
    if (
      event.key === 'Escape' &&
      panelRef.current?.contains(event.target as Node)
    ) {
      event.stopPropagation();
      closeFxAdvanced();
    }
  };

  return (
    <div
      ref={panelRef}
      role="dialog"
      aria-modal="false"
      aria-labelledby={titleId}
      tabIndex={-1}
      onKeyDown={onKeyDown}
      data-fx-advanced=""
      style={pos ? { left: pos.x, top: pos.y } : { right: EDGE, top: EDGE }}
      className={cn(
        'fixed flex max-h-[calc(100dvh-2rem)] w-[min(24rem,calc(100vw-2rem))] flex-col overflow-hidden border outline-hidden',
        fx.on
          ? 'fx-see-through z-(--fx-z-pop) rounded-(--fx-r-l) border-(--fx-line) bg-(--fx-surface)/50 text-(--fx-ink) shadow-[0_8px_24px_var(--fx-shade)]'
          : 'z-(--z-sidebar) rounded-lg bg-popover text-popover-foreground shadow-lg',
      )}
    >
      <div
        ref={headerRef}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={() => {
          drag.current = null;
        }}
        className="flex shrink-0 cursor-move touch-none select-none items-center gap-2 border-b px-3 py-2"
      >
        <button
          type="button"
          data-fx-grip=""
          aria-label="Move panel"
          onKeyDown={onGripKey}
          className={cn(
            PRESSED_CLASS,
            'flex size-7 cursor-move items-center justify-center rounded-md',
          )}
        >
          <GripVertical className="size-4" aria-hidden="true" />
        </button>
        <h2 id={titleId} className="flex-1 text-sm font-semibold">
          Advanced settings
        </h2>
        <Button
          type="button"
          variant="ghost"
          mode="icon"
          size="sm"
          aria-label="Close"
          onClick={closeFxAdvanced}
        >
          <X />
        </Button>
      </div>
      <div className="flex min-h-0 flex-col gap-4 overflow-y-auto p-3">
        <MasterSwitch on={fx.on} onChange={fx.setOn} />
        {fx.on ? (
          <>
            <PresetBar fx={fx} />
            <Settings fx={fx} />
          </>
        ) : null}
      </div>
      {fx.on ? (
        <div className="flex shrink-0 items-center justify-end gap-3 border-t px-3 py-2">
          <button
            type="button"
            onClick={() => applyFxValues(fx, {})}
            className={cn(PRESSED_CLASS, LINK_BUTTON)}
          >
            Reset all
          </button>
        </div>
      ) : null}
    </div>
  );
}

/** Mounted once in the top bar's user menu; renders only while open. */
export function AdvancedSettings() {
  const fx = useFxControls();
  const open = useFxAdvancedOpen();
  if (!fx || !open || typeof document === 'undefined') return null;
  return createPortal(<Panel fx={fx} />, document.body);
}
