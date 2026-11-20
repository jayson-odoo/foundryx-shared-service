import { describe, expect, it } from 'vitest';
import * as mod from './file-display-type';

const { openedType } = mod;

const LISTED = [
  'image/png',
  'image/jpeg',
  'image/gif',
  'image/webp',
  'image/x-icon',
  'application/pdf',
  'text/plain',
  'application/zip',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  'application/vnd.openxmlformats-officedocument.presentationml.presentation',
  'audio/ogg',
  'audio/mpeg',
  'audio/mp4',
  'audio/aac',
  'audio/amr',
  'audio/webm',
  'video/mp4',
  'video/3gpp',
  'video/webm',
];

const kept = (t: string) => (t === 'text/plain' ? 'text/plain;charset=utf-8' : t);

describe('one display type list for every viewer (AC-52-05)', () => {
  it.each(LISTED)('%s keeps its type', (type) => {
    expect(openedType(type)).toBe(kept(type));
  });

  it.each(LISTED)('%s is matched case-blind with parameters dropped', (type) => {
    expect(openedType(type.toUpperCase() + '; x=1')).toBe(kept(type));
  });

  it('audio/ogg with codec parameters keeps the base type', () => {
    expect(openedType('audio/ogg; codecs=opus')).toBe('audio/ogg');
  });

  it.each(['video/webm', 'audio/webm', 'image/gif'])('%s keeps its type', (type) => {
    expect(openedType(type)).toBe(type);
  });

  it.each([
    'text/html',
    'image/svg+xml',
    'application/xhtml+xml',
    'text/xml',
    'application/javascript',
    '',
    'video/quicktime',
  ])('an unlisted %j type becomes a download type', (type) => {
    expect(openedType(type)).toBe('application/octet-stream');
  });

  it('there is a single helper, no second list', () => {
    expect('mediaType' in mod).toBe(false);
  });
});
