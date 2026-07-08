import { beforeEach, describe, expect, it } from 'vitest';
import {
  __resetMockQuickReplies,
  mockQuickReplyService as svc,
} from './quick-reply-service.mock';

beforeEach(() => __resetMockQuickReplies());

describe('mock quick-reply service', () => {
  it('lists seeded rows for a workspace, shortcut-sorted', async () => {
    const rows = await svc.list('wsp-1');
    expect(rows.length).toBe(2);
    expect(rows[0].shortcut).toBe('/hi');
    expect(rows.every((r) => r.workspaceId === 'wsp-1')).toBe(true);
  });

  it('creates a row (trimming shortcut + body)', async () => {
    const created = await svc.create('wsp-1', { shortcut: '  /new ', body: '  Hello  ' });
    expect(created.shortcut).toBe('/new');
    expect(created.body).toBe('Hello');
    const rows = await svc.list('wsp-1');
    expect(rows.some((r) => r.id === created.id)).toBe(true);
  });

  it('normalizes a blank shortcut to null', async () => {
    const created = await svc.create('wsp-1', { shortcut: '   ', body: 'No shortcut' });
    expect(created.shortcut).toBeNull();
  });

  it('rejects a duplicate shortcut within a workspace', async () => {
    await expect(svc.create('wsp-1', { shortcut: '/hi', body: 'dup' })).rejects.toThrow();
  });

  it('allows the same shortcut in a different workspace', async () => {
    const a = await svc.create('wsp-a', { shortcut: '/x', body: 'A' });
    const b = await svc.create('wsp-b', { shortcut: '/x', body: 'B' });
    expect(a.workspaceId).toBe('wsp-a');
    expect(b.workspaceId).toBe('wsp-b');
  });

  it('updates a row and clears a shortcut with explicit null', async () => {
    const created = await svc.create('wsp-1', { shortcut: '/greet', body: 'Hi' });
    const updated = await svc.update('wsp-1', created.id, { body: 'Hi there', shortcut: null });
    expect(updated.body).toBe('Hi there');
    expect(updated.shortcut).toBeNull();
  });

  it('rejects updating onto a shortcut already used by another row', async () => {
    const created = await svc.create('wsp-1', { shortcut: '/greet', body: 'Hi' });
    await expect(
      svc.update('wsp-1', created.id, { shortcut: '/hi' }),
    ).rejects.toThrow();
  });

  it('deletes a row', async () => {
    const created = await svc.create('wsp-1', { body: 'Bye' });
    await svc.remove('wsp-1', created.id);
    const rows = await svc.list('wsp-1');
    expect(rows.some((r) => r.id === created.id)).toBe(false);
  });
});
