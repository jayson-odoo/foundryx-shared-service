'use client';

import { useRef, useState } from 'react';
import { ImageIcon, LoaderCircleIcon, Trash2, Upload } from 'lucide-react';
import { toast } from 'sonner';
import type { BrandingAssetKind } from '@/types/branding';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

/** Client-side mirror of the backend caps (plan 03) — server re-validates. */
export const ASSET_CONSTRAINTS: Record<
  BrandingAssetKind,
  { accept: string[]; maxBytes: number; hint: string }
> = {
  logo: {
    accept: ['image/png', 'image/jpeg', 'image/svg+xml', 'image/webp'],
    maxBytes: 2 * 1024 * 1024,
    hint: 'PNG, JPG, SVG or WebP · max 2 MB. Used on the sign-in page, the top-left header and as the tab-icon fallback.',
  },
  favicon: {
    accept: [
      'image/png',
      'image/jpeg',
      'image/webp',
      'image/x-icon',
      'image/vnd.microsoft.icon',
    ],
    maxBytes: 512 * 1024,
    hint: 'Square image (PNG/ICO recommended) · max 512 KB. Falls back to the logo when empty — wordmark logos read poorly at 16 px, so a dedicated icon is recommended.',
  },
  illustration: {
    accept: ['image/png', 'image/jpeg', 'image/svg+xml', 'image/webp'],
    maxBytes: 2 * 1024 * 1024,
    hint: 'PNG, JPG, SVG or WebP · max 2 MB. Anchored to the bottom of the sign-in brand panel; leave empty for a clean panel.',
  },
};

export interface AssetUploadCardProps {
  kind: BrandingAssetKind;
  title: string;
  /** Current asset URL (null = not set). */
  url: string | null;
  canManage: boolean;
  /** Render the preview on the brand color (logo/illustration sit on the primary panel). */
  onBrandSurface?: boolean;
  onUpload: (file: File) => Promise<unknown>;
  onRemove: () => Promise<unknown>;
}

/** One branding asset slot — preview + upload/replace/remove. Uploads apply immediately. */
export function AssetUploadCard({
  kind,
  title,
  url,
  canManage,
  onBrandSurface = false,
  onUpload,
  onRemove,
}: AssetUploadCardProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const constraints = ASSET_CONSTRAINTS[kind];

  const pick = () => inputRef.current?.click();

  const handleFile = async (file: File | undefined) => {
    if (!file) return;
    if (!constraints.accept.includes(file.type)) {
      toast.error('Unsupported file type.');
      return;
    }
    if (file.size > constraints.maxBytes) {
      toast.error(
        `File too large — max ${Math.round(constraints.maxBytes / 1024)} KB.`,
      );
      return;
    }
    setBusy(true);
    try {
      await onUpload(file);
      toast.success(`${title} updated.`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Upload failed.');
    } finally {
      setBusy(false);
      if (inputRef.current) inputRef.current.value = '';
    }
  };

  const handleRemove = async () => {
    setBusy(true);
    try {
      await onRemove();
      toast.success(`${title} removed.`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Remove failed.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <CardHeader className="py-4">
        <CardTitle className="text-sm">{title}</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <div
          className={cn(
            'flex h-28 items-center justify-center overflow-hidden rounded-md border border-border',
            onBrandSurface ? 'bg-primary' : 'bg-muted',
          )}
        >
          {url ? (
            // Plain <img> on purpose — data-URLs (mock) and backend asset URLs alike.
             
            <img
              src={url}
              alt={title}
              className={cn(
                'max-h-20 max-w-[80%] object-contain',
                kind === 'favicon' && 'max-h-12',
              )}
            />
          ) : (
            <div className="flex flex-col items-center gap-1 text-muted-foreground">
              <ImageIcon className="size-6" />
              <span className="text-xs">Not set</span>
            </div>
          )}
        </div>
        <p className="text-xs text-muted-foreground">{constraints.hint}</p>
        {canManage && (
          <div className="flex items-center gap-2">
            <input
              ref={inputRef}
              type="file"
              accept={constraints.accept.join(',')}
              className="hidden"
              aria-label={`Upload ${title.toLowerCase()}`}
              onChange={(e) => void handleFile(e.target.files?.[0])}
            />
            <Button size="sm" variant="outline" onClick={pick} disabled={busy}>
              {busy ? (
                <LoaderCircleIcon className="size-3.5 animate-spin" />
              ) : (
                <Upload className="size-3.5" />
              )}
              {url ? 'Replace' : 'Upload'}
            </Button>
            {url && (
              <Button
                size="sm"
                variant="ghost"
                onClick={() => void handleRemove()}
                disabled={busy}
              >
                <Trash2 className="size-3.5" />
                Remove
              </Button>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
