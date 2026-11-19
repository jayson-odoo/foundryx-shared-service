'use client';

/**
 * Small pieces the core settings pages share under the Foundryx UIUX switch
 * (slice W4-SETTINGS): the signed-in user's name for a done toast's "by
 * whom", and a setting shown as plain text to someone who may read the page
 * but not change it (owner decision: view-only pages are plain text).
 */
import type { ReactNode } from 'react';
import { useSession } from 'next-auth/react';
import { FX_FIELD_LABEL } from '@/components/fx/fields';

/** The signed-in user's name; unknown where no session provider is mounted. */
export function useFxUserName(): string | undefined {
  try {
    return useSession()?.data?.user?.name ?? undefined;
  } catch {
    return undefined;
  }
}

/** A setting as plain text: its label above, its value below. */
export function FxPlainSetting({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col gap-1" data-fx-plain-setting="">
      <span className={FX_FIELD_LABEL}>{label}</span>
      <span className="text-sm text-(--fx-ink) break-words">{children}</span>
    </div>
  );
}
