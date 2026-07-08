'use client';

/**
 * Structured message bodies (plan 12 Slice 2): interactive (what the recipient
 * sees), the inbound "chose: …" reply badge, location cards, and contact cards.
 * Pure presentation — the composer builds these, the bubble renders them.
 */
import { ExternalLink, LayoutList, MapPin, Phone, User } from 'lucide-react';

import type {
  ContactCard,
  ContactsPayload,
  ConversationMessage,
  InteractiveDefinition,
  InteractiveReplyPayload,
  LocationPayload,
} from '@/types/omnichannel';

const STRUCTURED_TYPES = ['INTERACTIVE', 'INTERACTIVE_REPLY', 'LOCATION', 'CONTACTS', 'UNSUPPORTED'];

export function isStructuredMessage(message: ConversationMessage): boolean {
  return STRUCTURED_TYPES.includes(message.messageType);
}

function contactName(name: ContactCard['name']): string {
  if (typeof name === 'string') return name;
  return name.formatted_name || name.first_name || 'Contact';
}

function vcardHref(card: ContactCard): string {
  const name = contactName(card.name);
  const lines = ['BEGIN:VCARD', 'VERSION:3.0', `FN:${name}`];
  for (const p of card.phones) lines.push(`TEL;TYPE=${p.type ?? 'CELL'}:${p.phone}`);
  lines.push('END:VCARD');
  return `data:text/vcard;charset=utf-8,${encodeURIComponent(lines.join('\n'))}`;
}

function InteractiveCard({ def }: { def: InteractiveDefinition }) {
  return (
    <div className="space-y-1.5" data-testid="structured-interactive">
      {def.header?.type === 'text' && def.header.text && (
        <div className="text-sm font-semibold">{def.header.text}</div>
      )}
      {def.header && def.header.type !== 'text' && (
        <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
          {def.header.type} header
        </div>
      )}
      <p className="whitespace-pre-wrap break-words text-sm">{def.body}</p>
      {def.footer && <p className="text-xs text-muted-foreground">{def.footer}</p>}

      {def.kind === 'buttons' && (
        <div className="mt-1 flex flex-col gap-1">
          {def.buttons?.map((b) => (
            <span key={b.id} className="rounded-md border border-border px-2 py-1 text-center text-xs font-medium text-primary-accent">
              {b.title}
            </span>
          ))}
        </div>
      )}
      {def.kind === 'list' && (
        <div className="mt-1 space-y-1">
          <span className="flex items-center justify-center gap-1.5 rounded-md border border-border px-2 py-1 text-xs font-medium text-primary-accent">
            <LayoutList className="size-3.5" /> {def.list?.button}
          </span>
          {def.list?.sections.map((sec, i) => (
            <div key={i} className="text-xs text-muted-foreground">
              {sec.title && <div className="font-medium">{sec.title}</div>}
              {sec.rows.map((r) => (
                <div key={r.id} className="pl-2">
                  • {r.title}
                  {r.description ? ` — ${r.description}` : ''}
                </div>
              ))}
            </div>
          ))}
        </div>
      )}
      {def.kind === 'cta_url' && def.cta && (
        <a
          href={def.cta.url}
          target="_blank"
          rel="noreferrer"
          className="mt-1 flex items-center justify-center gap-1.5 rounded-md border border-border px-2 py-1 text-xs font-medium text-primary-accent"
        >
          <ExternalLink className="size-3.5" /> {def.cta.displayText}
        </a>
      )}
      {def.kind === 'location_request' && (
        <span className="mt-1 flex items-center justify-center gap-1.5 rounded-md border border-border px-2 py-1 text-xs font-medium text-primary-accent">
          <MapPin className="size-3.5" /> Send location
        </span>
      )}
    </div>
  );
}

function ReplyBadge({ payload }: { payload: InteractiveReplyPayload }) {
  return (
    <span
      className="inline-flex items-center gap-1 rounded-full bg-primary-soft px-2.5 py-1 text-xs font-medium text-primary-accent"
      data-testid="structured-reply"
    >
      chose: {payload.title}
    </span>
  );
}

function LocationCard({ payload }: { payload: LocationPayload }) {
  const maps = `https://www.google.com/maps/search/?api=1&query=${payload.lat},${payload.lng}`;
  return (
    <div className="space-y-1" data-testid="structured-location">
      <div className="flex items-center gap-1.5 text-sm font-medium">
        <MapPin className="size-4 text-primary-accent" />
        {payload.name || 'Location'}
      </div>
      {payload.address && <p className="text-xs text-muted-foreground">{payload.address}</p>}
      <p className="text-xs tabular-nums text-muted-foreground">
        {payload.lat}, {payload.lng}
      </p>
      <a
        href={maps}
        target="_blank"
        rel="noreferrer"
        className="inline-flex items-center gap-1 text-xs font-medium text-primary-accent underline underline-offset-2"
      >
        <ExternalLink className="size-3.5" /> Open in Maps
      </a>
    </div>
  );
}

function ContactsCard({ payload }: { payload: ContactsPayload }) {
  return (
    <div className="space-y-2" data-testid="structured-contacts">
      {payload.contacts.map((card, i) => (
        <div key={i} className="space-y-1">
          <div className="flex items-center gap-1.5 text-sm font-medium">
            <User className="size-4 text-primary-accent" />
            {contactName(card.name)}
          </div>
          {card.phones.map((p, j) => (
            <a
              key={j}
              href={`tel:${p.phone}`}
              className="flex items-center gap-1.5 text-xs text-primary-accent underline underline-offset-2"
            >
              <Phone className="size-3.5" /> {p.phone}
            </a>
          ))}
          <a
            href={vcardHref(card)}
            download={`${contactName(card.name)}.vcf`}
            className="inline-flex text-xs font-medium text-muted-foreground underline underline-offset-2"
          >
            Save contact
          </a>
        </div>
      ))}
    </div>
  );
}

export function MessageStructured({ message }: { message: ConversationMessage }) {
  switch (message.messageType) {
    case 'INTERACTIVE':
      return <InteractiveCard def={message.payload as InteractiveDefinition} />;
    case 'INTERACTIVE_REPLY':
      return <ReplyBadge payload={message.payload as InteractiveReplyPayload} />;
    case 'LOCATION':
      return <LocationCard payload={message.payload as LocationPayload} />;
    case 'CONTACTS':
      return <ContactsCard payload={message.payload as ContactsPayload} />;
    default:
      return (
        <p className="text-sm italic text-muted-foreground" data-testid="structured-unsupported">
          Unsupported message type
        </p>
      );
  }
}
