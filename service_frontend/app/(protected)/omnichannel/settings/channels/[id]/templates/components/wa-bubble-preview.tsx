'use client';

import { ExternalLink, Phone, Copy, Reply, Image as ImageIcon, FileText, Video } from 'lucide-react';
import type { WaTemplateDoc } from '@/types/whatsapp-template';
import { useFx } from '@/hooks/use-fx';

/** Substitute {{1}},{{2}}… with the provided sample values (preview only). */
function fill(text: string, examples: string[]): string {
  return (text || '').replace(/\{\{\s*(\d+)\s*\}\}/g, (_m, n) => {
    const v = examples[Number(n) - 1];
    return v && v.trim() ? v : `{{${n}}}`;
  });
}

const MEDIA_ICON = { IMAGE: ImageIcon, VIDEO: Video, DOCUMENT: FileText } as const;

/**
 * Live WhatsApp-bubble preview (plan 07 UX-6) - renders the doc exactly as a
 * recipient would see it, with sample values substituted. Read-only.
 */
export function WaBubblePreview({ doc }: { doc: WaTemplateDoc }) {
  return useFx() ? <FxWaBubblePreview doc={doc} /> : <WaBubblePreviewLegacy doc={doc} />;
}

/**
 * Foundryx UIUX switch only: the same bubble on theme tokens instead of the
 * raw WhatsApp wallpaper and link colours (gap audit "Raw colour"), so it
 * follows the palette and dark mode.
 */
function FxWaBubblePreview({ doc }: { doc: WaTemplateDoc }) {
  const headerExample = doc.header && doc.header.format === 'TEXT' ? doc.header.example ?? '' : '';
  return (
    <div className="rounded-(--fx-r-l) border border-(--fx-line) bg-(--fx-surface-2) p-3 sm:p-4" data-fx-bubble-preview="">
      <div className="mx-auto w-full max-w-sm rounded-(--fx-r-m) bg-(--fx-surface) px-3 py-2 text-(--fx-ink) shadow-[0_2px_8px_var(--fx-shade)]">
        {doc.header && doc.header.format !== 'TEXT' && (
          <div className="mb-2 flex h-28 items-center justify-center rounded-(--fx-r-m) bg-(--fx-surface-2) text-(--fx-ink-3)">
            {(() => {
              const Icon = MEDIA_ICON[doc.header.format] ?? ImageIcon;
              return <Icon aria-hidden="true" className="size-8" />;
            })()}
          </div>
        )}
        {doc.header && doc.header.format === 'TEXT' && doc.header.text && (
          <p className="mb-1 text-sm font-semibold">{fill(doc.header.text, headerExample ? [headerExample] : [])}</p>
        )}
        <p className="whitespace-pre-wrap text-sm [overflow-wrap:anywhere]">
          {fill(doc.body.text, doc.body.examples) || <span className="text-(--fx-ink-3)">Your message body</span>}
        </p>
        {doc.footer?.text && <p className="mt-1 text-xs text-(--fx-ink-3)">{doc.footer.text}</p>}
        {doc.buttons && doc.buttons.length > 0 && (
          <div className="mt-2 flex flex-col gap-1 border-t border-(--fx-line) pt-2">
            {doc.buttons.map((b, i) => {
              const Icon =
                b.type === 'URL' ? ExternalLink : b.type === 'PHONE_NUMBER' ? Phone : b.type === 'COPY_CODE' ? Copy : Reply;
              const label =
                b.type === 'COPY_CODE' ? `Copy code${b.example ? ` (${b.example})` : ''}` : b.text || '-';
              return (
                <div
                  key={i}
                  className="flex items-center justify-center gap-1.5 rounded-(--fx-r-s) py-1.5 text-sm font-semibold text-(--fx-link)"
                >
                  <Icon aria-hidden="true" className="size-4" />
                  {label}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

function WaBubblePreviewLegacy({ doc }: { doc: WaTemplateDoc }) {
  const headerExample = doc.header && doc.header.format === 'TEXT' ? doc.header.example ?? '' : '';
  return (
    <div className="rounded-xl bg-[#E5DDD5] p-3 sm:p-4">
      <div className="mx-auto w-full max-w-sm rounded-lg bg-white px-3 py-2 shadow-sm">
        {doc.header && doc.header.format !== 'TEXT' && (
          <div className="mb-2 flex h-28 items-center justify-center rounded-md bg-muted text-muted-foreground">
            {(() => {
              const Icon = MEDIA_ICON[doc.header.format] ?? ImageIcon;
              return <Icon className="size-8" />;
            })()}
          </div>
        )}
        {doc.header && doc.header.format === 'TEXT' && doc.header.text && (
          <p className="mb-1 text-sm font-semibold text-foreground">
            {fill(doc.header.text, headerExample ? [headerExample] : [])}
          </p>
        )}

        <p className="whitespace-pre-wrap text-sm text-foreground">
          {fill(doc.body.text, doc.body.examples) || (
            <span className="text-muted-foreground">Your message body…</span>
          )}
        </p>

        {doc.footer?.text && <p className="mt-1 text-xs text-muted-foreground">{doc.footer.text}</p>}

        {doc.buttons && doc.buttons.length > 0 && (
          <div className="mt-2 flex flex-col gap-1 border-t border-border pt-2">
            {doc.buttons.map((b, i) => {
              const Icon =
                b.type === 'URL'
                  ? ExternalLink
                  : b.type === 'PHONE_NUMBER'
                    ? Phone
                    : b.type === 'COPY_CODE'
                      ? Copy
                      : Reply;
              const label =
                b.type === 'COPY_CODE' ? `Copy code${b.example ? ` (${b.example})` : ''}` : b.text || '-';
              return (
                <div
                  key={i}
                  className="flex items-center justify-center gap-1.5 rounded-md py-1.5 text-sm font-medium text-[#00A5F4]"
                >
                  <Icon className="size-4" />
                  {label}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
