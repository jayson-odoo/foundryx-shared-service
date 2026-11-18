'use client';

/**
 * The media limits form with the Foundryx UIUX switch on (slice W2-WS). Same
 * five caps, the same rules and the same save request as with the switch off
 * (blank = Meta default as `null`, a number in MB stored as bytes and capped
 * at Meta's ceiling); what changes is how it reads:
 * - "Save media settings" is the page's red action, greyed with "Nothing
 *   changed yet." until a cap changes (today's button is disabled the same
 *   way).
 * - A size that is not a number shows its message under that field instead
 *   of a toast, and the field pulses.
 * - Saving ends with a done toast whose Undo writes the caps back as they
 *   were (the same settings endpoint, with the old values).
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { formatMb, mbToBytes } from '@/lib/media-size';
import { toast } from '@/lib/toast';
import { cn } from '@/lib/utils';
import { useOmnichannelSettings } from '@/hooks/use-omnichannel-settings';
import type {
  OmnichannelSettings,
  OmnichannelSettingsOverrides,
  OmnichannelSettingsUpdate,
} from '@/services/omnichannel-settings-service';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardHeader,
  CardHeading,
  CardTitle,
} from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  useRegisterMainAction,
  type FxMainActionSpec,
} from '@/components/fx/actions/page-actions-context';
import { pulseFxTarget } from '@/components/fx/actions/pulse';
import { FxField } from '@/components/fx/fields';
import { useFxUserName } from '../workspaces/components/use-fx-user-name';
import {
  CAPS,
  LoadingSkeleton,
  mimeLabel,
  seedValues,
  type CapValues,
} from './media-caps-form';

const capTarget = (key: keyof OmnichannelSettingsOverrides) =>
  `media-cap-${key}`;

/**
 * The save body for the typed values, exactly as the form with the switch
 * off builds it, or the caps whose value is not a size.
 */
export function fxMediaPayload(
  settings: OmnichannelSettings,
  values: CapValues,
):
  | { payload: OmnichannelSettingsUpdate }
  | { invalid: (keyof OmnichannelSettingsOverrides)[] } {
  const payload: OmnichannelSettingsUpdate = {};
  const invalid: (keyof OmnichannelSettingsOverrides)[] = [];
  for (const cap of CAPS) {
    const raw = values[cap.overrideKey].trim();
    if (raw === '') {
      payload[cap.overrideKey] = null;
      continue;
    }
    const mb = Number(raw);
    if (!Number.isFinite(mb) || mb <= 0) {
      invalid.push(cap.overrideKey);
      continue;
    }
    const ceiling = settings.effective[cap.effectiveKind].ceilingBytes;
    payload[cap.overrideKey] = Math.min(mbToBytes(mb), ceiling);
  }
  return invalid.length > 0 ? { invalid } : { payload };
}

export function FxMediaCapsForm() {
  const { settings, loading, error, saving, save, reload } =
    useOmnichannelSettings();
  const byWhom = useFxUserName();
  const [values, setValues] = useState<CapValues | null>(null);
  const [wrong, setWrong] = useState<(keyof OmnichannelSettingsOverrides)[]>(
    [],
  );

  useEffect(() => {
    if (settings) setValues(seedValues(settings));
  }, [settings]);

  const dirty = useMemo(() => {
    if (!settings || !values) return false;
    const base = seedValues(settings);
    return CAPS.some((c) => base[c.overrideKey] !== values[c.overrideKey]);
  }, [settings, values]);

  const onSave = async () => {
    if (!settings || !values) return;
    const built = fxMediaPayload(settings, values);
    if ('invalid' in built) {
      setWrong(built.invalid);
      pulseFxTarget(capTarget(built.invalid[0]));
      return;
    }
    setWrong([]);
    const before: OmnichannelSettingsUpdate = { ...settings.overrides };
    try {
      await save(built.payload);
      toast.fxDone({
        what: 'Media limits saved',
        byWhom,
        undo: () =>
          void save(before).catch(() =>
            toast.error("Couldn't undo. The new limits stay."),
          ),
      });
    } catch (e) {
      toast.error(
        e instanceof Error ? e.message : "Couldn't save the media limits.",
      );
    }
  };

  const onSaveRef = useRef(onSave);
  onSaveRef.current = onSave;
  const ready = Boolean(settings && values);
  const main = useMemo<FxMainActionSpec | null>(
    () =>
      ready
        ? {
            id: 'save-media',
            label: 'Save media settings',
            onClick: () => void onSaveRef.current(),
            working: saving,
            blocked: dirty ? undefined : { reason: 'Nothing changed yet.' },
          }
        : null,
    [ready, saving, dirty],
  );
  useRegisterMainAction(main);

  if (loading && !settings) return <LoadingSkeleton />;

  if (error && !settings) {
    return (
      <Card>
        <CardContent className="flex flex-col items-start gap-3 py-6">
          <p className="text-sm text-(--fx-ink-2)">{error}</p>
          <Button variant="outline" onClick={() => void reload()}>
            Try again
          </Button>
        </CardContent>
      </Card>
    );
  }

  if (!settings || !values) return null;

  return (
    <div className="grid grid-cols-1 gap-5 md:grid-cols-2 xl:grid-cols-3">
      {CAPS.map((cap) => {
        const eff = settings.effective[cap.effectiveKind];
        const ceilingMb = formatMb(eff.ceilingBytes);
        const isWrong = wrong.includes(cap.overrideKey);
        return (
          <Card key={cap.overrideKey}>
            <CardHeader>
              <CardHeading>
                <CardTitle>{cap.label}</CardTitle>
              </CardHeading>
            </CardHeader>
            <CardContent className="flex flex-col gap-4">
              <div className="flex flex-col gap-1.5">
                <Label htmlFor={`cap-${cap.overrideKey}`}>
                  Maximum size (MB)
                </Label>
                <FxField
                  message={
                    isWrong
                      ? 'Enter a size in MB, or leave it blank.'
                      : undefined
                  }
                >
                  <div data-fx-pulse-target={capTarget(cap.overrideKey)}>
                    <Input
                      id={`cap-${cap.overrideKey}`}
                      type="number"
                      min={0}
                      step="any"
                      inputMode="decimal"
                      placeholder={`Meta default (${ceilingMb} MB)`}
                      aria-invalid={isWrong ? true : undefined}
                      value={values[cap.overrideKey]}
                      onChange={(e) => {
                        const next = e.target.value;
                        setValues((v) =>
                          v ? { ...v, [cap.overrideKey]: next } : v,
                        );
                        if (isWrong)
                          setWrong((w) =>
                            w.filter((k) => k !== cap.overrideKey),
                          );
                      }}
                    />
                  </div>
                </FxField>
                {/* The wrong-size message takes this line's place, so nothing moves. */}
                <p
                  className={cn(
                    'text-xs text-(--fx-ink-3)',
                    isWrong && 'invisible',
                  )}
                >
                  Up to {ceilingMb} MB
                </p>
              </div>
              <div className="flex flex-col gap-1.5">
                <span className="text-xs font-medium text-(--fx-ink-3)">
                  Accepted types
                </span>
                <div className="flex flex-wrap gap-1.5">
                  {eff.acceptedMimes.map((mime) => (
                    <Badge
                      key={mime}
                      variant="outline"
                      appearance="outline"
                      className="font-normal"
                      title={mime}
                    >
                      {mimeLabel(mime)}
                    </Badge>
                  ))}
                </div>
              </div>
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}
