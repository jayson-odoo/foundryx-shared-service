'use client';

import { useRef, useState } from 'react';
import { Download, RotateCcw, Upload } from 'lucide-react';
import { toast } from 'sonner';
import type { BrandingTokens, ThemeName } from '@/types/branding';
import {
  buildTemplate,
  DREAMZ_DEFAULTS,
  emptyTokens,
  hasOverrides,
  isValidColor,
  normalizeHex,
  parseTemplateFile,
  TOKEN_DEFS,
  TOKEN_GROUP_LABELS,
  type TokenGroup,
} from '@/lib/branding-tokens';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';

export interface ThemeTokenEditorProps {
  /** Current draft (null = no overrides). */
  tokens: BrandingTokens | null;
  onChange: (next: BrandingTokens | null) => void;
  canManage: boolean;
}

const GROUP_ORDER: TokenGroup[] = ['brand', 'status', 'grey', 'surface'];

/**
 * The curated theme editor (sprint-2/03) — BOTH edit methods over the same
 * stored document: per-variable color pickers (grouped by section, light/dark
 * tabs) and download-template → modify → upload-JSON. Values equal to the
 * Dreamz default are treated as "not overridden".
 */
export function ThemeTokenEditor({
  tokens,
  onChange,
  canManage,
}: ThemeTokenEditorProps) {
  const [theme, setTheme] = useState<ThemeName>('light');
  const fileRef = useRef<HTMLInputElement>(null);

  const overrides = tokens?.[theme] ?? {};
  const defaults = DREAMZ_DEFAULTS[theme];

  const setValue = (key: string, raw: string) => {
    const next: BrandingTokens = tokens
      ? { light: { ...tokens.light }, dark: { ...tokens.dark } }
      : emptyTokens();
    const value = raw.trim();
    if (
      !value ||
      (isValidColor(value) &&
        normalizeHex(value) === normalizeHex(defaults[key]))
    ) {
      delete next[theme][key]; // back to default = drop the override
    } else {
      next[theme][key] = value; // kept raw while typing; validated on save/upload
    }
    onChange(hasOverrides(next) ? next : null);
  };

  const resetAll = () => onChange(null);

  const download = () => {
    const template = buildTemplate(tokens);
    const blob = new Blob([JSON.stringify(template, null, 2)], {
      type: 'application/json',
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'theme-tokens.json';
    a.click();
    URL.revokeObjectURL(url);
  };

  const uploadTemplate = async (file: File | undefined) => {
    if (!file) return;
    const { tokens: parsed, errors } = parseTemplateFile(await file.text());
    if (errors.length) {
      // Show exactly why — silent drops are forbidden.
      toast.error(
        <div className="flex flex-col gap-1">
          <span className="font-medium">Template rejected:</span>
          {errors.slice(0, 5).map((e) => (
            <span key={e} className="text-xs">
              {e}
            </span>
          ))}
          {errors.length > 5 && (
            <span className="text-xs">…and {errors.length - 5} more.</span>
          )}
        </div>,
      );
      return;
    }
    onChange(parsed);
    toast.success('Template applied — review and save.');
    if (fileRef.current) fileRef.current.value = '';
  };

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between gap-2 py-4">
        <CardTitle className="text-sm">Theme</CardTitle>
        <div className="flex items-center gap-2">
          {/* Light/Dark segmented control (each theme has its own values). */}
          <div className="flex items-center rounded-md border border-border p-0.5">
            {(['light', 'dark'] as const).map((t) => (
              <Button
                key={t}
                type="button"
                size="sm"
                variant={theme === t ? 'primary' : 'ghost'}
                className="h-7 px-3 capitalize"
                onClick={() => setTheme(t)}
              >
                {t}
              </Button>
            ))}
          </div>
          {canManage && (
            <>
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={download}
              >
                <Download className="size-3.5" />
                Download template
              </Button>
              <input
                ref={fileRef}
                type="file"
                accept="application/json,.json"
                className="hidden"
                aria-label="Upload theme template"
                onChange={(e) => void uploadTemplate(e.target.files?.[0])}
              />
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={() => fileRef.current?.click()}
              >
                <Upload className="size-3.5" />
                Upload template
              </Button>
              {hasOverrides(tokens) && (
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  onClick={resetAll}
                >
                  <RotateCcw className="size-3.5" />
                  Reset all
                </Button>
              )}
            </>
          )}
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-6">
        <p className="text-xs text-muted-foreground">
          Override only what you need — everything else keeps the default
          theme. Download the template to edit every value in one JSON file,
          or pick colors directly below.
        </p>
        {GROUP_ORDER.map((group) => (
          <div key={group} className="flex flex-col gap-2">
            <h4 className="text-xs font-semibold uppercase text-muted-foreground">
              {TOKEN_GROUP_LABELS[group]}
            </h4>
            <div className="grid grid-cols-1 gap-x-8 gap-y-1.5 md:grid-cols-2 xl:grid-cols-3">
              {TOKEN_DEFS.filter((d) => d.group === group).map((d) => {
                const overridden = overrides[d.key] !== undefined;
                const value = overrides[d.key] ?? defaults[d.key];
                const valid = isValidColor(value);
                return (
                  <div key={d.key} className="flex items-center gap-2">
                    {/* Native color input = the picker; hidden behind the swatch. */}
                    <label
                      className={cn(
                        'relative size-6 shrink-0 cursor-pointer rounded-md border',
                        overridden ? 'border-primary' : 'border-border',
                        !canManage && 'pointer-events-none',
                      )}
                      style={{
                        backgroundColor: valid ? value : defaults[d.key],
                      }}
                      title={
                        overridden
                          ? 'Overridden — click to change'
                          : 'Default — click to override'
                      }
                    >
                      <input
                        type="color"
                        className="absolute inset-0 size-full cursor-pointer opacity-0"
                        value={
                          valid
                            ? normalizeHex(value).slice(0, 7)
                            : normalizeHex(defaults[d.key])
                        }
                        disabled={!canManage}
                        aria-label={`${d.label} (${theme})`}
                        onChange={(e) => setValue(d.key, e.target.value)}
                      />
                    </label>
                    <span
                      className="min-w-0 flex-1 truncate text-sm"
                      title={d.label}
                    >
                      {d.label}
                      {overridden && (
                        <span className="ms-1.5 align-middle text-primary">
                          •
                        </span>
                      )}
                    </span>
                    <Input
                      className={cn(
                        'h-7 w-[7.5rem] font-mono text-xs uppercase',
                        !valid && 'border-destructive',
                      )}
                      value={value}
                      disabled={!canManage}
                      aria-label={`${d.label} hex value (${theme})`}
                      onChange={(e) => setValue(d.key, e.target.value)}
                    />
                    {canManage && overridden && (
                      <Button
                        type="button"
                        size="sm"
                        mode="icon"
                        variant="ghost"
                        className="size-7"
                        title="Reset to default"
                        onClick={() => setValue(d.key, '')}
                      >
                        <RotateCcw className="size-3.5" />
                      </Button>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
