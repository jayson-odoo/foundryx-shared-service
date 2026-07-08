'use client';

import { useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardHeading, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Skeleton } from '@/components/ui/skeleton';
import { formatMb, mbToBytes } from '@/lib/media-size';
import { useOmnichannelSettings } from '@/hooks/use-omnichannel-settings';
import type {
  MediaKind,
  OmnichannelSettings,
  OmnichannelSettingsOverrides,
  OmnichannelSettingsUpdate,
} from '@/services/omnichannel-settings-service';

interface CapConfig {
  overrideKey: keyof OmnichannelSettingsOverrides;
  effectiveKind: MediaKind;
  label: string;
}

// The 5 editable caps. Audio's cap also governs voice notes (they share the
// backend column), so its accepted-mimes come from the AUDIO effective entry.
const CAPS: CapConfig[] = [
  { overrideKey: 'imageMaxBytes', effectiveKind: 'IMAGE', label: 'Image' },
  { overrideKey: 'videoMaxBytes', effectiveKind: 'VIDEO', label: 'Video' },
  { overrideKey: 'audioMaxBytes', effectiveKind: 'AUDIO', label: 'Audio & voice notes' },
  { overrideKey: 'documentMaxBytes', effectiveKind: 'DOCUMENT', label: 'Document' },
  { overrideKey: 'stickerMaxBytes', effectiveKind: 'STICKER', label: 'Sticker' },
];

type CapValues = Record<keyof OmnichannelSettingsOverrides, string>;

/** Seed the MB-string inputs from the stored byte overrides (null → blank). */
function seedValues(settings: OmnichannelSettings): CapValues {
  const seed = {} as CapValues;
  for (const cap of CAPS) {
    const bytes = settings.overrides[cap.overrideKey];
    seed[cap.overrideKey] = bytes === null ? '' : formatMb(bytes);
  }
  return seed;
}

function LoadingSkeleton() {
  return (
    <div className="grid grid-cols-1 gap-5 md:grid-cols-2 xl:grid-cols-3">
      {CAPS.map((c) => (
        <Skeleton key={c.overrideKey} className="h-48 w-full rounded-lg" />
      ))}
    </div>
  );
}

/**
 * Per-type media size caps for the tenant default scope. Each card edits ONE
 * cap in MB (stored as bytes), shows the Meta ceiling, and lists the fixed
 * accepted MIME types read-only. A blank input = "use Meta default".
 */
export function MediaCapsForm() {
  const { settings, loading, error, saving, save, reload } = useOmnichannelSettings();
  const [values, setValues] = useState<CapValues | null>(null);

  useEffect(() => {
    if (settings) setValues(seedValues(settings));
  }, [settings]);

  const dirty = useMemo(() => {
    if (!settings || !values) return false;
    const base = seedValues(settings);
    return CAPS.some((c) => base[c.overrideKey] !== values[c.overrideKey]);
  }, [settings, values]);

  if (loading && !settings) return <LoadingSkeleton />;

  if (error && !settings) {
    return (
      <Card>
        <CardContent className="flex flex-col items-start gap-3 py-6">
          <p className="text-sm text-muted-foreground">{error}</p>
          <Button variant="outline" onClick={() => void reload()}>
            Retry
          </Button>
        </CardContent>
      </Card>
    );
  }

  if (!settings || !values) return null;

  const onSave = async () => {
    const payload: OmnichannelSettingsUpdate = {};
    for (const cap of CAPS) {
      const raw = values[cap.overrideKey].trim();
      if (raw === '') {
        payload[cap.overrideKey] = null;
        continue;
      }
      const mb = Number(raw);
      if (!Number.isFinite(mb) || mb <= 0) {
        toast.error(`Enter a valid size in MB for ${cap.label}, or leave it blank.`);
        return;
      }
      const ceiling = settings.effective[cap.effectiveKind].ceilingBytes;
      payload[cap.overrideKey] = Math.min(mbToBytes(mb), ceiling);
    }
    try {
      await save(payload);
      toast.success('Media limits saved.');
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not save media limits.');
    }
  };

  return (
    <div className="flex flex-col gap-5">
      <div className="grid grid-cols-1 gap-5 md:grid-cols-2 xl:grid-cols-3">
        {CAPS.map((cap) => {
          const eff = settings.effective[cap.effectiveKind];
          const ceilingMb = formatMb(eff.ceilingBytes);
          return (
            <Card key={cap.overrideKey}>
              <CardHeader>
                <CardHeading>
                  <CardTitle>{cap.label}</CardTitle>
                </CardHeading>
              </CardHeader>
              <CardContent className="flex flex-col gap-4">
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor={`cap-${cap.overrideKey}`}>Maximum size (MB)</Label>
                  <Input
                    id={`cap-${cap.overrideKey}`}
                    type="number"
                    min={0}
                    step="any"
                    inputMode="decimal"
                    placeholder={`Meta default (${ceilingMb} MB)`}
                    value={values[cap.overrideKey]}
                    onChange={(e) =>
                      setValues((v) => (v ? { ...v, [cap.overrideKey]: e.target.value } : v))
                    }
                  />
                  <p className="text-xs text-muted-foreground">max {ceilingMb} MB</p>
                </div>
                <div className="flex flex-col gap-1.5">
                  <span className="text-xs font-medium text-muted-foreground">Accepted types</span>
                  <div className="flex flex-wrap gap-1.5">
                    {eff.acceptedMimes.map((mime) => (
                      <Badge
                        key={mime}
                        variant="outline"
                        appearance="outline"
                        className="font-normal"
                      >
                        {mime}
                      </Badge>
                    ))}
                  </div>
                </div>
              </CardContent>
            </Card>
          );
        })}
      </div>
      <div>
        <Button onClick={() => void onSave()} disabled={saving || !dirty}>
          {saving ? 'Saving…' : 'Save'}
        </Button>
      </div>
    </div>
  );
}
