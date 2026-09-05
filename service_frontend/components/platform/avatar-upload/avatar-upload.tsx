'use client';

import { useRef, useState } from 'react';
import { LoaderCircleIcon, Pencil, Trash2, Upload } from 'lucide-react';
import { toast } from '@/lib/toast';
import { AVATAR_ACCEPT, validateAvatarFile } from '@/lib/image-crop';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { UserAvatar } from '@/components/platform/user-avatar';
import { AvatarCropDialog } from './crop-dialog';

export interface AvatarUploadProps {
  /** Identity for the preview (initials fallback). */
  name: string | null;
  email: string;
  /** Current avatar URL (null = initials). */
  avatar: string | null;
  /** Receives the CROPPED square blob (≤512px, webp/png). */
  onUpload: (blob: Blob) => Promise<unknown>;
  onRemove: () => Promise<unknown>;
  disabled?: boolean;
}

/**
 * Shared avatar slot (plan 06 D5) - the avatar with a pen badge. No avatar:
 * the pen opens the file picker directly; with one: a small menu (change /
 * remove). The square crop dialog sits between pick and upload. Changes apply
 * immediately (branding-asset convention), no Edit-toggle coupling.
 */
export function AvatarUpload({
  name,
  email,
  avatar,
  onUpload,
  onRemove,
  disabled = false,
}: AvatarUploadProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [pickedFile, setPickedFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);

  const pick = () => inputRef.current?.click();

  const handleFile = (file: File | undefined) => {
    if (!file) return;
    const problem = validateAvatarFile(file);
    if (problem) {
      toast.error(problem);
      if (inputRef.current) inputRef.current.value = '';
      return;
    }
    setPickedFile(file);
  };

  const handleCropped = async (blob: Blob) => {
    try {
      await onUpload(blob);
      toast.success('Avatar updated.');
      setPickedFile(null);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Upload failed.');
      throw e; // keep the dialog open so the user can retry
    } finally {
      if (inputRef.current) inputRef.current.value = '';
    }
  };

  const handleRemove = async () => {
    setBusy(true);
    try {
      await onRemove();
      toast.success('Avatar removed.');
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Remove failed.');
    } finally {
      setBusy(false);
    }
  };

  const penBadge = (
    <span
      className="absolute -bottom-0.5 -end-0.5 inline-flex size-6 items-center justify-center rounded-full border border-border bg-background text-muted-foreground shadow-sm transition-colors hover:text-primary"
      aria-hidden
    >
      {busy ? (
        <LoaderCircleIcon className="size-3.5 animate-spin" />
      ) : (
        <Pencil className="size-3" />
      )}
    </span>
  );

  return (
    <div className="relative inline-flex">
      <input
        ref={inputRef}
        type="file"
        accept={AVATAR_ACCEPT.join(',')}
        className="hidden"
        aria-label="Upload avatar"
        onChange={(e) => handleFile(e.target.files?.[0])}
      />
      <UserAvatar user={{ name, email, avatar }} size="lg" />
      {!disabled &&
        (avatar ? (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                aria-label="Edit avatar"
                className="absolute inset-0 cursor-pointer rounded-full"
                disabled={busy}
              >
                {penBadge}
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" side="bottom">
              <DropdownMenuItem onSelect={pick}>
                <Upload />
                Change photo
              </DropdownMenuItem>
              <DropdownMenuItem
                variant="destructive"
                onSelect={() => void handleRemove()}
              >
                <Trash2 />
                Remove photo
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        ) : (
          <button
            type="button"
            aria-label="Upload avatar"
            className="absolute inset-0 cursor-pointer rounded-full"
            onClick={pick}
            disabled={busy}
          >
            {penBadge}
          </button>
        ))}
      <AvatarCropDialog
        file={pickedFile}
        onCancel={() => {
          setPickedFile(null);
          if (inputRef.current) inputRef.current.value = '';
        }}
        onCropped={handleCropped}
      />
    </div>
  );
}
