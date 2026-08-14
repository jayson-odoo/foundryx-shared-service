'use client';

import { useState, type CSSProperties } from 'react';
import { Moon, Sun } from 'lucide-react';
import type { BrandingTokens, ThemeName } from '@/types/branding';
import { effectiveTokens } from '@/lib/branding-tokens';
import { toAbsoluteUrl } from '@/lib/helpers';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

export interface BrandingPreviewProps {
  slogan: string | null;
  appName: string | null;
  logoUrl: string | null;
  illustrationUrl: string | null;
  tokens: BrandingTokens | null;
}

const FOUNDRYX_LOGO = '/media/foundryx/foundryx-logo.png';

/**
 * Live preview (sprint-2/03) - renders the two surfaces a tenant brands most:
 * the sign-in page and the app header, against the DRAFT values (unsaved edits
 * included) so contrast problems are visible before saving. Scoped via inline
 * CSS variables on the wrapper - the rest of the app stays untouched.
 */
export function BrandingPreview({
  slogan,
  appName,
  logoUrl,
  illustrationUrl,
  tokens,
}: BrandingPreviewProps) {
  const [theme, setTheme] = useState<ThemeName>('light');
  const t = effectiveTokens(tokens, theme);

  // Draft palette as scoped vars - keys mirror what the app consumes.
  const scope: CSSProperties = {
    ['--pv-primary' as string]: t['primary'],
    ['--pv-primary-soft' as string]: t['primary-soft'],
    ['--pv-surface' as string]: t['light'],
    ['--pv-surface-soft' as string]: t['light-soft'],
    ['--pv-border' as string]: t['grey-200'],
    ['--pv-text' as string]: t['grey-900'],
    ['--pv-muted' as string]: t['grey-500'],
    ['--pv-success' as string]: t['success'],
    ['--pv-danger' as string]: t['danger'],
    ['--pv-warning' as string]: t['warning'],
    ['--pv-info' as string]: t['info'],
  };

  const logo = logoUrl ?? toAbsoluteUrl(FOUNDRYX_LOGO);

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between gap-2 py-4">
        <CardTitle className="text-sm">Preview</CardTitle>
        <div className="flex items-center rounded-md border border-border p-0.5">
          {(['light', 'dark'] as const).map((opt) => (
            <Button
              key={opt}
              type="button"
              size="sm"
              variant={theme === opt ? 'primary' : 'ghost'}
              className="h-7 px-3 capitalize"
              onClick={() => setTheme(opt)}
            >
              {opt === 'light' ? (
                <Sun className="size-3.5" />
              ) : (
                <Moon className="size-3.5" />
              )}
              {opt}
            </Button>
          ))}
        </div>
      </CardHeader>
      <CardContent
        className="grid grid-cols-1 gap-4 lg:grid-cols-2"
        style={scope}
      >
        {/* ── Sign-in page ───────────────────────────────────────────── */}
        <div className="flex flex-col gap-1.5">
          <span className="text-xs font-medium text-muted-foreground">
            Sign-in page
          </span>
          <div
            className="grid h-56 grid-cols-2 overflow-hidden rounded-lg border"
            style={{ borderColor: 'var(--pv-border)' }}
          >
            <div
              className="relative flex flex-col p-4"
              style={{ backgroundColor: 'var(--pv-primary)' }}
            >
              <img
                src={logo}
                alt="Logo"
                className="h-5 w-auto max-w-[70%] self-start object-contain"
              />
              {slogan && (
                <p className="mt-2 font-heading text-xs font-semibold text-white">
                  {slogan}
                </p>
              )}
              {illustrationUrl && (
                <img
                  src={illustrationUrl}
                  alt=""
                  className="mt-auto max-h-24 w-full self-center object-contain"
                />
              )}
            </div>
            <div
              className="flex flex-col justify-center gap-2 p-4"
              style={{
                backgroundColor: 'var(--pv-surface)',
                color: 'var(--pv-text)',
              }}
            >
              <span className="font-heading text-xs font-semibold">
                {appName ? `Welcome to ${appName}.` : 'Welcome back.'}
              </span>
              {['Email', 'Password'].map((f) => (
                <div key={f} className="flex flex-col gap-0.5">
                  <span
                    className="text-[10px]"
                    style={{ color: 'var(--pv-muted)' }}
                  >
                    {f}
                  </span>
                  <div
                    className="h-5 rounded border"
                    style={{
                      borderColor: 'var(--pv-border)',
                      backgroundColor: 'var(--pv-surface-soft)',
                    }}
                  />
                </div>
              ))}
              <div
                className="mt-1 flex h-6 items-center justify-center rounded text-[10px] font-medium text-white"
                style={{ backgroundColor: 'var(--pv-primary)' }}
              >
                Sign In
              </div>
            </div>
          </div>
        </div>

        {/* ── App shell ──────────────────────────────────────────────── */}
        <div className="flex flex-col gap-1.5">
          <span className="text-xs font-medium text-muted-foreground">
            App header & components
          </span>
          <div
            className="flex h-56 flex-col overflow-hidden rounded-lg border"
            style={{
              borderColor: 'var(--pv-border)',
              backgroundColor: 'var(--pv-surface)',
              color: 'var(--pv-text)',
            }}
          >
            <div
              className="flex items-center gap-2 border-b px-3 py-2"
              style={{ borderColor: 'var(--pv-border)' }}
            >
              {/* Primary chip + logo - exactly how the sidebar header renders it. */}
              <span
                className="inline-flex h-6 items-center rounded-md px-1.5"
                style={{ backgroundColor: 'var(--pv-primary)' }}
              >
                {logoUrl ? (
                  <img
                    src={logoUrl}
                    alt="Logo"
                    className="h-3.5 w-auto max-w-24 object-contain"
                  />
                ) : (
                  <span className="text-[9px] font-medium text-white">Your logo</span>
                )}
              </span>
              <div className="ms-auto flex items-center gap-1.5">
                {['var(--pv-muted)', 'var(--pv-muted)'].map((c, i) => (
                  <div
                    key={i}
                    className="size-4 rounded-full opacity-40"
                    style={{ backgroundColor: c }}
                  />
                ))}
              </div>
            </div>
            <div className="flex flex-col gap-2.5 p-3">
              <div className="flex items-center gap-2">
                <div
                  className="flex h-6 items-center rounded px-2.5 text-[10px] font-medium text-white"
                  style={{ backgroundColor: 'var(--pv-primary)' }}
                >
                  Primary action
                </div>
                <div
                  className="flex h-6 items-center rounded border px-2.5 text-[10px] font-medium"
                  style={{ borderColor: 'var(--pv-border)' }}
                >
                  Secondary
                </div>
              </div>
              <div className="flex items-center gap-1.5">
                {(
                  [
                    ['Active', 'var(--pv-success)'],
                    ['Pending', 'var(--pv-warning)'],
                    ['Failed', 'var(--pv-danger)'],
                    ['Info', 'var(--pv-info)'],
                  ] as const
                ).map(([label, color]) => (
                  <span
                    key={label}
                    className="flex items-center gap-1 rounded-full border px-1.5 py-0.5 text-[9px]"
                    style={{
                      borderColor: 'var(--pv-border)',
                      backgroundColor: 'var(--pv-surface-soft)',
                    }}
                  >
                    <span
                      className="size-1.5 rounded-full"
                      style={{ backgroundColor: color }}
                    />
                    {label}
                  </span>
                ))}
              </div>
              <div
                className={cn('rounded-md p-2 text-[10px]')}
                style={{
                  backgroundColor: 'var(--pv-primary-soft)',
                  color: 'var(--pv-text)',
                }}
              >
                Soft primary surface - banners, selected rows, highlights.
              </div>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
