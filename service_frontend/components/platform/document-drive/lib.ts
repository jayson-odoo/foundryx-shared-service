import {
  File as FileIcon,
  FileArchive,
  FileImage,
  FileSpreadsheet,
  FileText,
  FileType,
  type LucideIcon,
} from 'lucide-react';
import type { FileRow } from '@/types/documents';

/** Human-readable byte size. */
export function formatBytes(bytes: number): string {
  if (bytes <= 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.min(units.length - 1, Math.floor(Math.log(bytes) / Math.log(1024)));
  const value = bytes / 1024 ** i;
  return `${value >= 100 || i === 0 ? Math.round(value) : value.toFixed(1)} ${units[i]}`;
}

const ext = (name: string) => name.split('.').pop()?.toLowerCase() ?? '';

/** Icon for a file by extension family (mirrors the preview/mime split). */
export function fileIcon(name: string): LucideIcon {
  const e = ext(name);
  if (['png', 'jpg', 'jpeg', 'webp', 'gif'].includes(e)) return FileImage;
  if (e === 'pdf') return FileType;
  if (['xlsx', 'xls', 'csv'].includes(e)) return FileSpreadsheet;
  if (['doc', 'docx', 'txt', 'rtf'].includes(e)) return FileText;
  if (['zip', 'rar', '7z', 'tar', 'gz'].includes(e)) return FileArchive;
  return FileIcon;
}

/** Whether a file can preview inline (image/pdf). */
export function canPreview(file: FileRow): boolean {
  const e = ext(file.name);
  return ['png', 'jpg', 'jpeg', 'webp', 'gif', 'pdf'].includes(e);
}
