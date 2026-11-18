'use client';

/**
 * The Theme panel (playbook 0.71.0 "Theme" and "Settings > Master switch").
 *
 * With the Foundryx UIUX switch off it holds only the master switch, the one
 * thing the playbook adds to an existing system while off. With it on: Mode
 * (Light, Dark, Auto), Palette (only the chosen mode's three; Auto shows both,
 * headed), Font pick cards, the Size slider, then the master switch. Mode is
 * next-themes' own setting, shared with the user menu's Dark Mode switch.
 * Palette, font and size are saved per browser (`fx_theme` cookie).
 *
 * The "Advanced settings" link (shown only while on) arrives with the
 * Advanced settings panel; until then there is nothing for it to open.
 */
import { useId, useState } from 'react';
import { useTheme } from 'next-themes';
import {
  FX_DARK_PALETTES,
  FX_FONTS,
  FX_LIGHT_PALETTES,
  FX_SCALES,
  type FxDarkPalette,
  type FxFont,
  type FxLightPalette,
} from '@/lib/fx/cookies';
import { FX_PLAYBOOK_VERSION, FX_SWITCH_NAME } from '@/lib/fx/version';
import { cn } from '@/lib/utils';
import { useFxControls } from '@/hooks/use-fx';
import { PRESSED_CLASS } from '@/components/ui/primitive-classes';
import { Slider, SliderThumb } from '@/components/ui/slider';
import { Switch } from '@/components/ui/switch';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';

type Mode = 'light' | 'dark' | 'system';

/** Palette names and their three preview colours (background, surface, link). */
const PALETTE_INFO: Record<
  FxLightPalette | FxDarkPalette,
  { name: string; dots: string[] }
> = {
  slate: {
    name: 'Slate',
    dots: ['bg-[#F1F5F9]', 'bg-[#FFFFFF]', 'bg-[#1D4ED8]'],
  },
  sand: {
    name: 'Sand',
    dots: ['bg-[#F5F2EC]', 'bg-[#FFFFFF]', 'bg-[#0F5E9C]'],
  },
  mint: {
    name: 'Mint',
    dots: ['bg-[#EDF5F2]', 'bg-[#FFFFFF]', 'bg-[#0F766E]'],
  },
  midnight: {
    name: 'Midnight',
    dots: ['bg-[#0B1220]', 'bg-[#111A2B]', 'bg-[#93C5FD]'],
  },
  graphite: {
    name: 'Graphite',
    dots: ['bg-[#121214]', 'bg-[#1C1C1F]', 'bg-[#A5C8FF]'],
  },
  forest: {
    name: 'Forest',
    dots: ['bg-[#0B1512]', 'bg-[#12201B]', 'bg-[#7DD3C0]'],
  },
};

/** Font names (full name is the card's tooltip), short card names, and the
 *  class that draws the card's "Aa" in that font. */
const FONT_INFO: Record<FxFont, { name: string; short: string; face: string }> =
  {
    geist: {
      name: 'Geist',
      short: 'Geist',
      face: "font-['Geist',system-ui,sans-serif]",
    },
    jakarta: {
      name: 'Plus Jakarta Sans',
      short: 'Jakarta',
      face: "font-['Plus_Jakarta_Sans',system-ui,sans-serif]",
    },
    inter: {
      name: 'Inter',
      short: 'Inter',
      face: "font-['Inter',system-ui,sans-serif]",
    },
    manrope: {
      name: 'Manrope',
      short: 'Manrope',
      face: "font-['Manrope',system-ui,sans-serif]",
    },
    dmsans: {
      name: 'DM Sans',
      short: 'DM Sans',
      face: "font-['DM_Sans',system-ui,sans-serif]",
    },
  };

const NORMAL_SCALE = 90;

/** The size slider's value text: "Normal (90%)" at the middle step. */
export function scaleLabel(scale: number): string {
  return scale === NORMAL_SCALE ? `Normal (${scale}%)` : `${scale}%`;
}

const SECTION_LABEL =
  'text-xs font-semibold uppercase tracking-wide text-(--fx-ink-3)';

const CARD =
  'flex min-w-0 flex-col items-center gap-1.5 rounded-(--fx-r-m) border border-(--fx-line) bg-(--fx-surface) px-1 py-2 text-xs font-semibold text-(--fx-ink-2) hover:border-(--fx-ink-3) hover:bg-(--fx-surface-2) hover:text-(--fx-ink) aria-pressed:border-(--fx-link) aria-pressed:bg-(--fx-link-bg) aria-pressed:text-(--fx-ink)';

function PaletteCards<P extends FxLightPalette | FxDarkPalette>({
  palettes,
  value,
  onPick,
}: {
  palettes: readonly P[];
  value: P;
  onPick: (palette: P) => void;
}) {
  return (
    <div className="grid grid-cols-3 gap-2">
      {palettes.map((key) => (
        <button
          key={key}
          type="button"
          aria-pressed={value === key}
          onClick={() => onPick(key)}
          className={cn(PRESSED_CLASS, CARD)}
        >
          <span className="flex gap-1" aria-hidden="true">
            {PALETTE_INFO[key].dots.map((dot) => (
              <i
                key={dot}
                className={cn(
                  'size-3.5 rounded-full border border-(--fx-line-2)',
                  dot,
                )}
              />
            ))}
          </span>
          {PALETTE_INFO[key].name}
        </button>
      ))}
    </div>
  );
}

/** The master switch row: "Foundryx UIUX (0.71.0)", the version a little
 *  smaller, regular weight and lower contrast, as part of the label. */
function MasterSwitch({
  on,
  onChange,
}: {
  on: boolean;
  onChange: (on: boolean) => void;
}) {
  const id = useId();
  return (
    <div className="flex items-center justify-between gap-3">
      <label htmlFor={id} className="text-sm font-semibold">
        {FX_SWITCH_NAME}{' '}
        <span className="text-[0.85em] font-normal text-[var(--fx-ink-3,var(--muted-foreground))]">
          ({FX_PLAYBOOK_VERSION})
        </span>
      </label>
      <Switch id={id} checked={on} onCheckedChange={onChange} />
    </div>
  );
}

export function ThemePanel() {
  const fx = useFxControls();
  const { theme: rawMode, setTheme: setMode } = useTheme();
  const [draftScale, setDraftScale] = useState<number | null>(null);
  const sizeLabelId = useId();

  if (!fx) return null;

  if (!fx.on) {
    return <MasterSwitch on={false} onChange={fx.setOn} />;
  }

  const mode: Mode =
    rawMode === 'light' || rawMode === 'dark' ? rawMode : 'system';
  const scaleIndex = FX_SCALES.indexOf(fx.theme.scale);
  const shownScale =
    draftScale === null ? fx.theme.scale : FX_SCALES[draftScale];

  return (
    <div className="flex flex-col gap-4 text-(--fx-ink)">
      <section className="flex flex-col gap-2">
        <span className={SECTION_LABEL}>Mode</span>
        <ToggleGroup
          type="single"
          variant="outline"
          aria-label="Mode"
          value={mode}
          onValueChange={(next) => next && setMode(next)}
          className="w-full"
        >
          <ToggleGroupItem value="light" className="flex-1">
            Light
          </ToggleGroupItem>
          <ToggleGroupItem value="dark" className="flex-1">
            Dark
          </ToggleGroupItem>
          <ToggleGroupItem value="system" className="flex-1">
            Auto
          </ToggleGroupItem>
        </ToggleGroup>
      </section>

      {mode !== 'dark' && (
        <section className="flex flex-col gap-2">
          <span className={SECTION_LABEL}>
            {mode === 'system' ? 'Light palette' : 'Palette'}
          </span>
          <PaletteCards
            palettes={FX_LIGHT_PALETTES}
            value={fx.theme.pal}
            onPick={(pal) => fx.setTheme({ pal })}
          />
        </section>
      )}
      {mode !== 'light' && (
        <section className="flex flex-col gap-2">
          <span className={SECTION_LABEL}>
            {mode === 'system' ? 'Dark palette' : 'Palette'}
          </span>
          <PaletteCards
            palettes={FX_DARK_PALETTES}
            value={fx.theme.dpal}
            onPick={(dpal) => fx.setTheme({ dpal })}
          />
        </section>
      )}

      <section className="flex flex-col gap-2">
        <span className={SECTION_LABEL}>Font</span>
        <div className="grid grid-cols-5 gap-1.5">
          {FX_FONTS.map((key) => (
            <button
              key={key}
              type="button"
              aria-pressed={fx.theme.font === key}
              aria-label={FONT_INFO[key].name}
              title={
                FONT_INFO[key].short === FONT_INFO[key].name
                  ? undefined
                  : FONT_INFO[key].name
              }
              onClick={() => fx.setTheme({ font: key })}
              className={cn(PRESSED_CLASS, CARD)}
            >
              <span
                className={cn('text-lg leading-none', FONT_INFO[key].face)}
                aria-hidden="true"
              >
                Aa
              </span>
              <span className="max-w-full">{FONT_INFO[key].short}</span>
            </button>
          ))}
        </div>
      </section>

      <section className="flex flex-col gap-2">
        <span id={sizeLabelId} className={SECTION_LABEL}>
          Size
        </span>
        <div className="flex items-center gap-3">
          <span className="text-xs" aria-hidden="true">
            A
          </span>
          <Slider
            min={0}
            max={FX_SCALES.length - 1}
            step={1}
            value={[draftScale ?? scaleIndex]}
            onValueChange={([index]) => setDraftScale(index)}
            onValueCommit={([index]) => {
              setDraftScale(null);
              fx.setTheme({ scale: FX_SCALES[index] });
            }}
            aria-labelledby={sizeLabelId}
          >
            <SliderThumb
              aria-labelledby={sizeLabelId}
              aria-valuetext={`${shownScale}%`}
            />
          </Slider>
          <span className="text-lg" aria-hidden="true">
            A
          </span>
        </div>
        <span className="text-center text-xs text-(--fx-ink-2)">
          {scaleLabel(shownScale)}
        </span>
      </section>

      <div className="border-t border-(--fx-line) pt-3">
        <MasterSwitch on onChange={fx.setOn} />
      </div>
    </div>
  );
}
