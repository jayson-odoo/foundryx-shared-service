/**
 * The words the drive uses under the Foundryx UIUX switch (slice W3-DOCS),
 * kept pure so the explorer, the trash and their tests share them.
 */
import { useSession } from 'next-auth/react';
import { fxCount } from '@/components/fx/list/fx-words';

export interface DriveTargets {
  folderIds: string[];
  fileIds: string[];
}

/** "1 item" / "12 items". */
export function fxItems(n: number): string {
  return `${fxCount(n)} ${n === 1 ? 'item' : 'items'}`;
}

/** What a set of drive entries is called in a toast or a question: the one
 *  entry's name, else "3 items". */
export function fxTargetsName(targets: DriveTargets, nameOf: (kind: 'folder' | 'file', id: string) => string | undefined): string {
  const total = targets.folderIds.length + targets.fileIds.length;
  if (total === 1) {
    const name = targets.folderIds.length
      ? nameOf('folder', targets.folderIds[0])
      : nameOf('file', targets.fileIds[0]);
    if (name) return name;
  }
  return fxItems(total);
}

/** What a typed delete-forever asks for: the one entry's name, else how many
 *  (owner decision: type the record's name or number). */
export function fxPurgeExpected(targets: DriveTargets, nameOf: (kind: 'folder' | 'file', id: string) => string | undefined): string {
  const total = targets.folderIds.length + targets.fileIds.length;
  if (total === 1) {
    const name = targets.folderIds.length
      ? nameOf('folder', targets.folderIds[0])
      : nameOf('file', targets.fileIds[0]);
    if (name) return name;
  }
  return String(total);
}

/** Who did it, for a done toast's "by Kay Tan". */
export function useFxActorName(): string | undefined {
  const { data } = useSession();
  return data?.user?.name ?? undefined;
}

/** "1 link" / "12 links". */
export function fxLinks(n: number): string {
  return `${fxCount(n)} ${n === 1 ? 'link' : 'links'}`;
}
