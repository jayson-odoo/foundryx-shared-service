'use client';

/**
 * The share dialog's expiry, password and upload limits under the Foundryx
 * UIUX switch (slice W3-DOCS).
 *
 * - Expiry is a day in the playbook date field. A picked day is sent as the
 *   very instant today's date input sends for that day (`shareExpiryInstant`,
 *   23:59:59 UTC), and today's lower bound (the UTC day) is kept. The moment
 *   the link stops working is shown in the viewer's zone, 12-hour.
 * - Turning Expiry or Password on opens its field; the request goes out only
 *   once a day is picked or a password is set, the same request today's
 *   controls send for the same input. (With the switch off those two switches
 *   cannot open their field: reported, not changed.)
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

/** The instant a share expires for a picked day: what today's date input
 *  sends (`new Date(`${day}T23:59:59Z`).toISOString()`). */
export function shareExpiryInstant(dayKey: string): string {
  return new Date(`${dayKey}T23:59:59Z`).toISOString();
}

/** Today's lower bound for the expiry day: the UTC calendar day, as today. */
export function shareExpiryMinDay(now: Date = new Date()): string {
  return now.toISOString().slice(0, 10);
}

export function FxShareAdvanced({
  share,
  patch,
}: {
  share: ShareRow;
  patch: (body: ShareUpdatePayload) => Promise<void>;
}) {
  const { formatDateTime } = useDatetime();
  const [expiry, setExpiry] = useState<string | null>(share.expiresAt ? share.expiresAt.slice(0, 10) : null);
  const [expiryOpen, setExpiryOpen] = useState(share.expiresAt !== null);
  const [password, setPassword] = useState('');
  const [passwordOpen, setPasswordOpen] = useState(false);
  const [todayKey] = useState(() => shareExpiryMinDay());
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
              void patch({ expiresAt: shareExpiryInstant(expiry) });
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
            onChange={(day) => {
              setExpiry(day);
              if (day && day >= todayKey) void patch({ expiresAt: shareExpiryInstant(day) });
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
