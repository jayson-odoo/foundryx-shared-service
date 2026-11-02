// The fixed set of types a fetched file may be displayed with.
const SERVED_FILE_TYPES: readonly string[] = [
  'image/png',
  'image/jpeg',
  'image/gif',
  'image/webp',
  'application/pdf',
  'text/plain',
  'image/x-icon',
  'application/zip',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  'application/vnd.openxmlformats-officedocument.presentationml.presentation',
];

/** The type a fetched file is opened with: a listed base type, else a download. */
export function openedType(rawType: string): string {
  const base = rawType.toLowerCase().split(';')[0].trim();
  if (base === 'text/plain') return 'text/plain;charset=utf-8';
  return SERVED_FILE_TYPES.includes(base) ? base : 'application/octet-stream';
}
