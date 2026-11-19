'use client';

/**
 * The system banner bar (playbook 0.71.0 "System banners"), mounted by the
 * Foundryx UIUX top bar.
 *
 * - One thin bar across the top of the app, above the top bar, full width;
 *   never a pop-up.
 * - The `warn` or `info` chip set; one line with a muted icon at the left
 *   and at most one text button at the right. On phones the text may take two
 *   lines and the button goes under it at the right.
 * - Several at once: the most urgent shows, with "1 of 2" and ‹ › to step.
 * - It takes its height from the top of the page: it publishes its real
 *   height as `--shell-top-offset`, which the top bar, side panel, page header
 *   and content already read, so nothing slides under it.
 * - It slides down on arrival and up when it closes (0.3 s).
 */
import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { Info, TriangleAlert } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { FxIcon } from '@/components/fx/icons';
import {
  closeSystemBanner,
  useSystemBanners,
  type FxBanner,
} from './banner-store';

const TONE: Record<FxBanner['tone'], string> = {
  warn: 'bg-(--fx-warn-bg) text-(--fx-warn-ink)',
  info: 'bg-(--fx-info-bg) text-(--fx-info-ink)',
};

/** How long the bar takes to slide up when its last banner goes. */
const LEAVE_MS = 300;

function setOffset(px: number | null): void {
  const style = document.documentElement.style;
  if (px === null) style.removeProperty('--shell-top-offset');
  else style.setProperty('--shell-top-offset', `${px}px`);
}

export function FxSystemBannerHost() {
  const banners = useSystemBanners();
  const [index, setIndex] = useState(0);
  // The last banner shown, kept on screen while the bar slides away.
  const [leaving, setLeaving] = useState<FxBanner | null>(null);
  const lastShown = useRef<FxBanner | null>(null);
  const barRef = useRef<HTMLDivElement>(null);

  const count = banners.length;
  const at = Math.min(index, Math.max(0, count - 1));
  const current = count ? banners[at] : null;

  useEffect(() => {
    if (current) {
      lastShown.current = current;
      setLeaving(null);
      return;
    }
    if (!lastShown.current) return;
    setLeaving(lastShown.current);
    lastShown.current = null;
    const t = setTimeout(() => setLeaving(null), LEAVE_MS);
    return () => clearTimeout(t);
  }, [current]);

  const shown = current ?? leaving;

  // The bar's real height pushes the shell down (0 while there is none).
  useEffect(() => {
    const el = barRef.current;
    if (!current || !el) {
      setOffset(0);
      return;
    }
    const publish = () => setOffset(el.offsetHeight);
    publish();
    const observer = new ResizeObserver(publish);
    observer.observe(el);
    return () => observer.disconnect();
  }, [current]);

  useEffect(() => () => setOffset(null), []);

  if (!shown) return null;

  const step = (delta: number) =>
    setIndex((value) => (Math.min(value, count - 1) + delta + count) % count);

  const action = shown.action;
  return (
    <div
      ref={barRef}
      role="status"
      data-fx-banner={shown.tone}
      className={cn(
        'fixed inset-x-0 top-0 z-(--z-banner) border-b border-(--fx-line) px-4 py-1.5 text-sm duration-(--fx-t-open) ease-(--fx-ease-out)',
        TONE[shown.tone],
        current
          ? 'animate-in slide-in-from-top'
          : 'animate-out slide-out-to-top fill-mode-forwards',
      )}
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <div className="flex min-w-0 flex-1 basis-60 items-start gap-2">
          {shown.tone === 'warn' ? (
            <TriangleAlert
              className="mt-0.5 size-4 shrink-0 opacity-70"
              aria-hidden="true"
            />
          ) : (
            <Info
              className="mt-0.5 size-4 shrink-0 opacity-70"
              aria-hidden="true"
            />
          )}
          <span className="min-w-0">{shown.text}</span>
        </div>
        <div className="ms-auto flex items-center gap-1">
          {count > 1 && current && (
            <span className="flex items-center gap-0.5">
              <Button
                variant="ghost"
                mode="icon"
                size="sm"
                aria-label="Previous message"
                className="size-7 text-current hover:bg-(--fx-shade)"
                onClick={() => step(-1)}
              >
                <FxIcon name="previous" size={16} />
              </Button>
              <span className="text-xs tabular-nums">
                {at + 1} of {count}
              </span>
              <Button
                variant="ghost"
                mode="icon"
                size="sm"
                aria-label="Next message"
                className="size-7 text-current hover:bg-(--fx-shade)"
                onClick={() => step(1)}
              >
                <FxIcon name="next" size={16} />
              </Button>
            </span>
          )}
          {action &&
            (action.href ? (
              <Button
                asChild
                variant="fx-text"
                size="sm"
                className="text-current underline-offset-2 hover:underline"
              >
                <Link href={action.href}>{action.label}</Link>
              </Button>
            ) : (
              <Button
                variant="fx-text"
                size="sm"
                disabled={action.disabled}
                className="text-current underline-offset-2 hover:underline"
                onClick={action.onClick}
              >
                {action.label}
              </Button>
            ))}
          {shown.hide && (
            <Button
              variant="ghost"
              mode="icon"
              size="sm"
              aria-label={shown.hide.label}
              title={shown.hide.label}
              className="size-7 text-current hover:bg-(--fx-shade)"
              onClick={shown.hide.onHide}
            >
              <FxIcon name="previous" size={16} className="rotate-90" />
            </Button>
          )}
          {shown.closable && (
            <Button
              variant="ghost"
              mode="icon"
              size="sm"
              aria-label="Close"
              className="size-7 text-current hover:bg-(--fx-shade)"
              onClick={() => closeSystemBanner(shown.id)}
            >
              <FxIcon name="close" size={16} />
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}
