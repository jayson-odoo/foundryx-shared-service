/**
 * `useMenu` breadcrumb/current-item resolution (fix round 1): the resolver
 * must prefer the LONGEST matching path (an exact match first), not the
 * first document-order hit - `isActive` is a `startsWith` match, so a short
 * sibling path like `/documents` is also "active" while viewing a longer
 * sibling route (`/documents/settings`), and the wrong one used to win.
 */
import { describe, expect, it } from 'vitest';
import { renderHook } from '@testing-library/react';
import { useMenu } from './use-menu';
import type { MenuItem } from '@/config/types';

const documentsGroup: MenuItem[] = [
  {
    title: 'Documents',
    children: [
      { title: 'All documents', path: '/documents' },
      { title: 'Shared links', path: '/documents/shares' },
      { title: 'Document types', path: '/documents/types' },
      { title: 'Settings', path: '/documents/settings' },
    ],
  },
];

const developersGroup: MenuItem[] = [
  {
    title: 'Developers',
    children: [
      { title: 'Logs', path: '/developers/logs' },
      { title: 'Log settings', path: '/developers/logs/settings' },
    ],
  },
];

describe('useMenu longest-match resolution', () => {
  it('Documents > Settings resolves to Settings, not the shorter sibling All documents', () => {
    const { result } = renderHook(() => useMenu('/documents/settings'));
    const current = result.current.getCurrentItem(documentsGroup);
    expect(current?.title).toBe('Settings');
    const crumb = result.current.getBreadcrumb(documentsGroup);
    expect(crumb.map((c) => c.title)).toEqual(['Documents', 'Settings']);
  });

  it('Documents > All documents still resolves correctly on its own exact route', () => {
    const { result } = renderHook(() => useMenu('/documents'));
    const current = result.current.getCurrentItem(documentsGroup);
    expect(current?.title).toBe('All documents');
  });

  it('Developers > Logs > Settings resolves to Log settings, not the shorter sibling Logs', () => {
    const { result } = renderHook(() => useMenu('/developers/logs/settings'));
    const current = result.current.getCurrentItem(developersGroup);
    expect(current?.title).toBe('Log settings');
    const crumb = result.current.getBreadcrumb(developersGroup);
    expect(crumb.map((c) => c.title)).toEqual(['Developers', 'Log settings']);
  });

  it('Developers > Logs still resolves correctly on its own exact route', () => {
    const { result } = renderHook(() => useMenu('/developers/logs'));
    const current = result.current.getCurrentItem(developersGroup);
    expect(current?.title).toBe('Logs');
  });
});
