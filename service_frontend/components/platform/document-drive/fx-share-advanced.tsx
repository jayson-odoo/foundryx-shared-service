'use client';

/**
 * The share dialog's expiry, password and upload limits under the Foundryx
 * UIUX switch (slice W3-DOCS).
 *
 * - Expiry is a day in the playbook date field, in the user's zone
 *   (`share-expiry.ts`): a picked day is sent as the instant that day ends
 *   there, the earliest day is today there, and a share opened again shows
 *   the same day. The moment the link stops working is shown in that zone,
 *   12-hour.
 * - Turning Expiry or Password on opens its field; the request goes out only
 *   once a day is picked or a password is set, the same request the old
 *   look's controls send for the same input.
 * - The password field is masked and never shows a set password.
 * - Upload limits are today's fields and requests.
 */
import { useEffect, useState } from 'react';
import { Lock } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { FxDateField, FX_FIELD_LABEL } from '@/components/fx/fields';
import { useDatetime } from '@/hooks/use-datetime';
import type { ShareRow, ShareUpdatePayload } from '@/types/documents';
import { shareExpiryDay, shareExpiryInstant, shareExpiryMinDay } from './share-expiry';

export function FxShareAdvanced({
  share,
  patch,
}: {
  share: ShareRow;
  patch: (body: ShareUpdatePayload) => Promise<void>;
}) {
  const { formatDateTime, timeZone } = useDatetime();
  const [expiry, setExpiry] = useState<string | null>(() => shareExpiryDay(share.expiresAt, timeZone));
  const [expiryOpen, setExpiryOpen] = useState(share.expiresAt !== null);
  const [password, setPassword] = useState('');
  const [passwordOpen, setPasswordOpen] = useState(false);
  const [todayKey] = useState(() => shareExpiryMinDay(timeZone));
  const isPublicEdit = share.generalAccess === 'public' && share.capability === 'edit';

  // A share that gains or loses its expiry elsewhere follows here.
  useEffect(() => {
    if (share.expiresAt !== null) setExpiryOpen(true);
  }, [share.expiresAt]);
  useEffect(() => {
    if (share.hasPassword) {
      setPasswordOpen(false);
      setPassword('');
    }
  }, [share.hasPassword]);

  return (
    <div className="grid gap-3 rounded-(--fx-r-m) border border-(--fx-line) bg-(--fx-surface-2) p-3">
      <div className="flex items-center justify-between gap-2">
        <Label htmlFor="share-expiry" className={FX_FIELD_LABEL}>
          Expiry date
        </Label>
        <Switch
          id="share-expiry"
          checked={expiryOpen}
          onCheckedChange={(on) => {
            setExpiryOpen(on);
            if (!on) {
              setExpiry(null);
              if (share.expiresAt !== null) void patch({ expiresAt: null });
            } else if (expiry) {
              void patch({ expiresAt: shareExpiryInstant(expiry, timeZone) });
            }
          }}
        />
      </div>
      {expiryOpen && (
        <div className="grid gap-1">
          <FxDateField
            aria-label="Expiry date"
            value={expiry}
            minDate={todayKey}
            timeZone={timeZone}
            onChange={(day) => {
              setExpiry(day);
              if (day && day >= todayKey) void patch({ expiresAt: shareExpiryInstant(day, timeZone) });
            }}
          />
          {share.expiresAt && (
            <p className="mt-4 text-sm text-(--fx-ink-2)" data-testid="share-expiry-moment">
              {share.isExpired ? 'Stopped working ' : 'Stops working '}
              {formatDateTime(share.expiresAt)}
            </p>
          )}
        </div>
      )}

      <div className="flex items-center justify-between gap-2">
        <Label htmlFor="share-pw" className={`${FX_FIELD_LABEL} flex items-center gap-1.5`}>
          <Lock className="size-3.5" aria-hidden="true" /> Password
        </Label>
        <Switch
          id="share-pw"
          checked={share.hasPassword || passwordOpen}
          onCheckedChange={(on) => {
            setPasswordOpen(on && !share.hasPassword);
            if (!on) {
              setPassword('');
              if (share.hasPassword) void patch({ password: null });
            }
          }}
        />
      </div>
      {passwordOpen && !share.hasPassword && (
        <div className="flex items-center gap-2">
          <Input
            type="password"
            autoComplete="new-password"
            value={password}
            aria-label="Share password"
            onChange={(e) => setPassword(e.target.value)}
          />
          <Button
            type="button"
            variant="fx-quiet"
            disabled={!password.trim()}
            onClick={() => void patch({ password })}
          >
            Set password
          </Button>
        </div>
      )}
      {share.hasPassword && <p className="text-sm text-(--fx-ink-2)">Password set.</p>}

      {isPublicEdit && (
        <div className="grid grid-cols-2 gap-2">
          <div className="grid gap-1">
            <Label htmlFor="share-max-uploads" className={FX_FIELD_LABEL}>
              Max uploads
            </Label>
            <Input
              id="share-max-uploads"
              type="number"
              min={1}
              defaultValue={share.maxUploads ?? ''}
              placeholder="50"
              onBlur={(e) => void patch({ maxUploads: e.target.value ? Number(e.target.value) : null })}
            />
          </div>
          <div className="grid gap-1">
            <Label htmlFor="share-max-mb" className={FX_FIELD_LABEL}>
              Max total MB
            </Label>
            <Input
              id="share-max-mb"
              type="number"
              min={1}
              defaultValue={share.maxTotalMb ?? ''}
              placeholder="200"
              onBlur={(e) => void patch({ maxTotalMb: e.target.value ? Number(e.target.value) : null })}
            />
          </div>
        </div>
      )}
    </div>
  );
}
