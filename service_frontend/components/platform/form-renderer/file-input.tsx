'use client';

/**
 * File-pick input (plan sprint-3/01, Phase A) — the answer is the serializable
 * `FormFileAnswer[]` (key/name/size/mime). Picked `File` objects are held in an
 * internal ref keyed by a `local:<uuid>` placeholder; upload wiring (Phase B)
 * resolves those placeholders to real storage keys, so nothing extra leaks into
 * the public API. Size/mime are checked at PICK time — a rejected file shows an
 * inline error and is dropped (never silently accepted).
 */
import { useRef, useState } from 'react';
import { X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';
import type { FormFileAnswer, FormFileValidation } from '@/types/forms';

export interface FileInputProps {
  value: FormFileAnswer[];
  onChange: (value: FormFileAnswer[]) => void;
  config?: FormFileValidation;
  disabled?: boolean;
  invalid?: boolean;
  id?: string;
}

/** Map of placeholder key → the live File (module-local, never serialized). */
const FILE_REGISTRY = new Map<string, File>();

/** Phase-B upload wiring reads the staged File for a `local:` answer key. */
export function stagedFile(key: string): File | undefined {
  return FILE_REGISTRY.get(key);
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function FileInput({ value, onChange, config, disabled, invalid, id }: FileInputProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [pickError, setPickError] = useState<string | null>(null);

  const onPick = (e: React.ChangeEvent<HTMLInputElement>) => {
    const picked = Array.from(e.target.files ?? []);
    if (picked.length === 0) return;
    setPickError(null);

    const maxBytes = config?.maxSizeMb != null ? config.maxSizeMb * 1024 * 1024 : null;
    const allowed = config?.allowedMimes;
    const accepted: FormFileAnswer[] = [];
    for (const file of picked) {
      if (maxBytes != null && file.size > maxBytes) {
        setPickError(`"${file.name}" exceeds the ${config?.maxSizeMb} MB limit.`);
        continue;
      }
      if (allowed && allowed.length > 0 && !allowed.includes(file.type)) {
        setPickError(`"${file.name}" is not an allowed file type.`);
        continue;
      }
      const key = `local:${crypto.randomUUID()}`;
      FILE_REGISTRY.set(key, file);
      accepted.push({ key, name: file.name, size: file.size, mime: file.type });
    }

    let next = [...value, ...accepted];
    if (config?.maxCount != null && next.length > config.maxCount) {
      next = next.slice(0, config.maxCount);
      setPickError(`At most ${config.maxCount} file${config.maxCount === 1 ? '' : 's'} allowed.`);
    }
    onChange(next);
    if (inputRef.current) inputRef.current.value = '';
  };

  const remove = (key: string) => {
    FILE_REGISTRY.delete(key);
    onChange(value.filter((f) => f.key !== key));
  };

  const atMax = config?.maxCount != null && value.length >= config.maxCount;

  return (
    <div className="space-y-2">
      <Input
        ref={inputRef}
        id={id}
        type="file"
        multiple={config?.maxCount !== 1}
        accept={config?.allowedMimes?.join(',')}
        disabled={disabled || atMax}
        aria-invalid={invalid || undefined}
        onChange={onPick}
      />
      {value.length > 0 && (
        <ul className="space-y-1">
          {value.map((file) => (
            <li
              key={file.key}
              className="flex items-center justify-between gap-2 rounded-md border border-border bg-muted/40 px-2.5 py-1.5 text-sm"
            >
              <span className="min-w-0 flex-1 truncate">{file.name}</span>
              <span className="shrink-0 text-xs text-muted-foreground">{formatBytes(file.size)}</span>
              {!disabled && (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="size-6 shrink-0 p-0"
                  aria-label={`Remove ${file.name}`}
                  onClick={() => remove(file.key)}
                >
                  <X className="size-4" />
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
      {pickError && <p className={cn('text-xs text-destructive')}>{pickError}</p>}
    </div>
  );
}
