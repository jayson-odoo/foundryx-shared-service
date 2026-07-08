'use client';

/**
 * Interactive / location / contacts builder dialogs (plan 12 Slice 2).
 * Each returns a typed input the composer hands to the send hook; the bubble
 * then renders what the recipient sees. Free-form → the composer only exposes
 * these while the 24h window is open.
 */
import { useRef, useState } from 'react';
import { LocateFixed, Plus, Trash2 } from 'lucide-react';

import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { SearchSelect } from '@/components/platform/search-select';
import type {
  ContactCard,
  InteractiveDefinition,
  InteractiveKind,
  InteractiveListSection,
  SendContactsInput,
  SendInteractiveInput,
  SendLocationInput,
} from '@/types/omnichannel';

const KIND_OPTIONS: { value: InteractiveKind; label: string }[] = [
  { value: 'buttons', label: 'Reply buttons' },
  { value: 'list', label: 'List menu' },
  { value: 'cta_url', label: 'Call-to-action link' },
  { value: 'location_request', label: 'Request location' },
];
const HEADER_OPTIONS = [
  { value: 'none', label: 'No header' },
  { value: 'text', label: 'Text' },
  { value: 'image', label: 'Image' },
  { value: 'video', label: 'Video' },
  { value: 'document', label: 'Document' },
];

const MAX_BUTTONS = 3;
const MAX_LIST_ROWS = 10;

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <label className="text-sm font-medium">{label}</label>
      {children}
    </div>
  );
}

// ── Interactive builder ──────────────────────────────────────────────────────
export function InteractiveBuilderDialog({
  open,
  onOpenChange,
  isSending,
  onSubmit,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  isSending: boolean;
  onSubmit: (input: SendInteractiveInput) => Promise<boolean>;
}) {
  const [kind, setKind] = useState<InteractiveKind>('buttons');
  const [headerType, setHeaderType] = useState('none');
  const [headerText, setHeaderText] = useState('');
  const [headerFile, setHeaderFile] = useState<File | null>(null);
  const [body, setBody] = useState('');
  const [footer, setFooter] = useState('');
  const [buttons, setButtons] = useState<{ id: string; title: string }[]>([{ id: 'b1', title: '' }]);
  const [listButton, setListButton] = useState('');
  const [sections, setSections] = useState<InteractiveListSection[]>([
    { title: '', rows: [{ id: 'r1', title: '', description: '' }] },
  ]);
  const [ctaText, setCtaText] = useState('');
  const [ctaUrl, setCtaUrl] = useState('');
  const fileRef = useRef<HTMLInputElement>(null);

  const reset = () => {
    setKind('buttons');
    setHeaderType('none');
    setHeaderText('');
    setHeaderFile(null);
    setBody('');
    setFooter('');
    setButtons([{ id: 'b1', title: '' }]);
    setListButton('');
    setSections([{ title: '', rows: [{ id: 'r1', title: '', description: '' }] }]);
    setCtaText('');
    setCtaUrl('');
  };

  const totalRows = sections.reduce((n, s) => n + s.rows.length, 0);
  const isMediaHeader = headerType === 'image' || headerType === 'video' || headerType === 'document';

  const buildDefinition = (): InteractiveDefinition => {
    const def: InteractiveDefinition = { kind, body: body.trim() };
    if (headerType === 'text' && headerText.trim()) def.header = { type: 'text', text: headerText.trim() };
    else if (isMediaHeader) def.header = { type: headerType as 'image' | 'video' | 'document' };
    if (footer.trim()) def.footer = footer.trim();
    if (kind === 'buttons') def.buttons = buttons.map((b) => ({ id: b.id, title: b.title.trim() }));
    else if (kind === 'list')
      def.list = {
        button: listButton.trim(),
        sections: sections.map((s) => ({
          ...(s.title?.trim() ? { title: s.title.trim() } : {}),
          rows: s.rows.map((r) => ({
            id: r.id,
            title: r.title.trim(),
            ...(r.description?.trim() ? { description: r.description.trim() } : {}),
          })),
        })),
      };
    else if (kind === 'cta_url') def.cta = { displayText: ctaText.trim(), url: ctaUrl.trim() };
    return def;
  };

  const ready = (() => {
    if (!body.trim()) return false;
    if (isMediaHeader && !headerFile) return false;
    if (kind === 'buttons') return buttons.length >= 1 && buttons.every((b) => b.title.trim());
    if (kind === 'list')
      return (
        !!listButton.trim() &&
        totalRows >= 1 &&
        totalRows <= MAX_LIST_ROWS &&
        sections.every((s) => s.rows.every((r) => r.title.trim()))
      );
    if (kind === 'cta_url') return !!ctaText.trim() && !!ctaUrl.trim();
    return true; // location_request
  })();

  const submit = async () => {
    const ok = await onSubmit({ definition: buildDefinition(), headerFile: isMediaHeader ? headerFile : null });
    if (ok) {
      reset();
      onOpenChange(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Interactive message</DialogTitle>
          <DialogDescription>
            Build reply buttons, a list, a link button, or a location request.
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="max-h-[70vh] space-y-4 overflow-y-auto">
          <Field label="Type">
            <SearchSelect
              options={KIND_OPTIONS}
              value={kind}
              onChange={(v) => setKind((v as InteractiveKind) || 'buttons')}
              ariaLabel="Interactive type"
              className="w-full"
            />
          </Field>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <Field label="Header">
              <SearchSelect
                options={HEADER_OPTIONS}
                value={headerType}
                onChange={(v) => {
                  setHeaderType(v || 'none');
                  setHeaderFile(null);
                }}
                ariaLabel="Header type"
                className="w-full"
              />
            </Field>
            {headerType === 'text' && (
              <Field label="Header text">
                <Input value={headerText} onChange={(e) => setHeaderText(e.target.value)} maxLength={60} />
              </Field>
            )}
            {isMediaHeader && (
              <Field label="Header file">
                <input
                  ref={fileRef}
                  type="file"
                  hidden
                  accept={
                    headerType === 'image'
                      ? 'image/png,image/jpeg'
                      : headerType === 'video'
                        ? 'video/mp4'
                        : '.pdf'
                  }
                  onChange={(e) => setHeaderFile(e.target.files?.[0] ?? null)}
                  data-testid="interactive-header-file"
                />
                <Button type="button" variant="outline" onClick={() => fileRef.current?.click()}>
                  {headerFile ? headerFile.name : 'Choose file'}
                </Button>
              </Field>
            )}
          </div>

          <Field label="Body">
            <Textarea value={body} onChange={(e) => setBody(e.target.value)} maxLength={1024} rows={3} data-testid="interactive-body" />
          </Field>
          <Field label="Footer">
            <Input value={footer} onChange={(e) => setFooter(e.target.value)} maxLength={60} placeholder="Optional" />
          </Field>

          {kind === 'buttons' && (
            <div className="space-y-2">
              <div className="text-sm font-medium">Buttons</div>
              {buttons.map((b, i) => (
                <div key={b.id} className="flex items-center gap-2">
                  <Input
                    value={b.title}
                    maxLength={20}
                    placeholder={`Button ${i + 1}`}
                    onChange={(e) =>
                      setButtons((prev) => prev.map((x) => (x.id === b.id ? { ...x, title: e.target.value } : x)))
                    }
                    data-testid="interactive-button"
                  />
                  {buttons.length > 1 && (
                    <Button variant="ghost" size="icon" aria-label="Remove button" onClick={() => setButtons((prev) => prev.filter((x) => x.id !== b.id))}>
                      <Trash2 className="size-4" />
                    </Button>
                  )}
                </div>
              ))}
              {buttons.length < MAX_BUTTONS && (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setButtons((prev) => [...prev, { id: `b${Date.now()}`, title: '' }])}
                  data-testid="interactive-add-button"
                >
                  <Plus className="size-4" /> Add button
                </Button>
              )}
            </div>
          )}

          {kind === 'list' && (
            <div className="space-y-3">
              <Field label="List button label">
                <Input value={listButton} onChange={(e) => setListButton(e.target.value)} maxLength={20} data-testid="interactive-list-button" />
              </Field>
              {sections.map((sec, si) => (
                <div key={si} className="space-y-2 rounded-md border p-2">
                  <Input
                    value={sec.title ?? ''}
                    placeholder="Section title (optional)"
                    maxLength={24}
                    onChange={(e) =>
                      setSections((prev) => prev.map((s, i) => (i === si ? { ...s, title: e.target.value } : s)))
                    }
                  />
                  {sec.rows.map((row, ri) => (
                    <div key={row.id} className="flex items-start gap-2">
                      <div className="flex-1 space-y-1">
                        <Input
                          value={row.title}
                          placeholder={`Row ${ri + 1} title`}
                          maxLength={24}
                          onChange={(e) =>
                            setSections((prev) =>
                              prev.map((s, i) =>
                                i === si
                                  ? { ...s, rows: s.rows.map((r) => (r.id === row.id ? { ...r, title: e.target.value } : r)) }
                                  : s,
                              ),
                            )
                          }
                          data-testid="interactive-row-title"
                        />
                        <Input
                          value={row.description ?? ''}
                          placeholder="Description (optional)"
                          maxLength={72}
                          onChange={(e) =>
                            setSections((prev) =>
                              prev.map((s, i) =>
                                i === si
                                  ? { ...s, rows: s.rows.map((r) => (r.id === row.id ? { ...r, description: e.target.value } : r)) }
                                  : s,
                              ),
                            )
                          }
                        />
                      </div>
                      {totalRows > 1 && (
                        <Button
                          variant="ghost"
                          size="icon"
                          aria-label="Remove row"
                          onClick={() =>
                            setSections((prev) =>
                              prev.map((s, i) => (i === si ? { ...s, rows: s.rows.filter((r) => r.id !== row.id) } : s)),
                            )
                          }
                        >
                          <Trash2 className="size-4" />
                        </Button>
                      )}
                    </div>
                  ))}
                  {totalRows < MAX_LIST_ROWS && (
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() =>
                        setSections((prev) =>
                          prev.map((s, i) =>
                            i === si ? { ...s, rows: [...s.rows, { id: `r${Date.now()}`, title: '', description: '' }] } : s,
                          ),
                        )
                      }
                      data-testid="interactive-add-row"
                    >
                      <Plus className="size-4" /> Add row
                    </Button>
                  )}
                </div>
              ))}
              {totalRows < MAX_LIST_ROWS && (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setSections((prev) => [...prev, { title: '', rows: [{ id: `r${Date.now()}`, title: '', description: '' }] }])}
                >
                  <Plus className="size-4" /> Add section
                </Button>
              )}
            </div>
          )}

          {kind === 'cta_url' && (
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <Field label="Button text">
                <Input value={ctaText} onChange={(e) => setCtaText(e.target.value)} maxLength={20} data-testid="interactive-cta-text" />
              </Field>
              <Field label="URL">
                <Input value={ctaUrl} onChange={(e) => setCtaUrl(e.target.value)} placeholder="https://…" data-testid="interactive-cta-url" />
              </Field>
            </div>
          )}
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button onClick={submit} disabled={!ready || isSending} data-testid="interactive-send">Send</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ── Location builder ─────────────────────────────────────────────────────────
export function LocationBuilderDialog({
  open,
  onOpenChange,
  isSending,
  onSubmit,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  isSending: boolean;
  onSubmit: (input: SendLocationInput) => Promise<boolean>;
}) {
  const [lat, setLat] = useState('');
  const [lng, setLng] = useState('');
  const [name, setName] = useState('');
  const [address, setAddress] = useState('');
  const [locating, setLocating] = useState(false);

  const ready = lat.trim() !== '' && lng.trim() !== '' && !Number.isNaN(Number(lat)) && !Number.isNaN(Number(lng));

  const useMyLocation = () => {
    if (!navigator.geolocation) return;
    setLocating(true);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setLat(String(pos.coords.latitude));
        setLng(String(pos.coords.longitude));
        setLocating(false);
      },
      () => setLocating(false),
    );
  };

  const submit = async () => {
    const ok = await onSubmit({
      lat: Number(lat),
      lng: Number(lng),
      name: name.trim() || undefined,
      address: address.trim() || undefined,
    });
    if (ok) {
      setLat('');
      setLng('');
      setName('');
      setAddress('');
      onOpenChange(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Share location</DialogTitle>
          <DialogDescription>Send a map location with optional name and address.</DialogDescription>
        </DialogHeader>
        <DialogBody className="space-y-4">
          <Button variant="outline" onClick={useMyLocation} disabled={locating} data-testid="location-use-mine">
            <LocateFixed className="size-4" /> {locating ? 'Locating…' : 'Use my location'}
          </Button>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Latitude">
              <Input value={lat} onChange={(e) => setLat(e.target.value)} inputMode="decimal" data-testid="location-lat" />
            </Field>
            <Field label="Longitude">
              <Input value={lng} onChange={(e) => setLng(e.target.value)} inputMode="decimal" data-testid="location-lng" />
            </Field>
          </div>
          <Field label="Name">
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Optional" />
          </Field>
          <Field label="Address">
            <Input value={address} onChange={(e) => setAddress(e.target.value)} placeholder="Optional" />
          </Field>
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button onClick={submit} disabled={!ready || isSending} data-testid="location-send">Send</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ── Contacts builder ─────────────────────────────────────────────────────────
export function ContactsBuilderDialog({
  open,
  onOpenChange,
  isSending,
  onSubmit,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  isSending: boolean;
  onSubmit: (input: SendContactsInput) => Promise<boolean>;
}) {
  const [name, setName] = useState('');
  const [phones, setPhones] = useState<{ id: string; phone: string; type: string }[]>([
    { id: 'p1', phone: '', type: 'CELL' },
  ]);

  const ready = name.trim() !== '' && phones.some((p) => p.phone.trim());

  const submit = async () => {
    const card: ContactCard = {
      name,
      phones: phones.filter((p) => p.phone.trim()).map((p) => ({ phone: p.phone.trim(), type: p.type })),
    };
    const ok = await onSubmit({ contacts: [card] });
    if (ok) {
      setName('');
      setPhones([{ id: 'p1', phone: '', type: 'CELL' }]);
      onOpenChange(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Share a contact</DialogTitle>
          <DialogDescription>Send a contact card with a name and phone numbers.</DialogDescription>
        </DialogHeader>
        <DialogBody className="space-y-4">
          <Field label="Name">
            <Input value={name} onChange={(e) => setName(e.target.value)} data-testid="contact-name" />
          </Field>
          <div className="space-y-2">
            <div className="text-sm font-medium">Phone numbers</div>
            {phones.map((p, i) => (
              <div key={p.id} className="flex items-center gap-2">
                <Input
                  value={p.phone}
                  placeholder={`Phone ${i + 1}`}
                  inputMode="tel"
                  onChange={(e) => setPhones((prev) => prev.map((x) => (x.id === p.id ? { ...x, phone: e.target.value } : x)))}
                  data-testid="contact-phone"
                />
                <div className="w-28 shrink-0">
                  <SearchSelect
                    options={[
                      { value: 'CELL', label: 'Mobile' },
                      { value: 'WORK', label: 'Work' },
                      { value: 'HOME', label: 'Home' },
                    ]}
                    value={p.type}
                    onChange={(v) => setPhones((prev) => prev.map((x) => (x.id === p.id ? { ...x, type: v || 'CELL' } : x)))}
                    ariaLabel="Phone type"
                    className="w-full"
                  />
                </div>
                {phones.length > 1 && (
                  <Button variant="ghost" size="icon" aria-label="Remove phone" onClick={() => setPhones((prev) => prev.filter((x) => x.id !== p.id))}>
                    <Trash2 className="size-4" />
                  </Button>
                )}
              </div>
            ))}
            <Button variant="outline" size="sm" onClick={() => setPhones((prev) => [...prev, { id: `p${Date.now()}`, phone: '', type: 'CELL' }])} data-testid="contact-add-phone">
              <Plus className="size-4" /> Add phone
            </Button>
          </div>
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button onClick={submit} disabled={!ready || isSending} data-testid="contact-send">Send</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
