import { describe, expect, it } from 'vitest';
import { MenuConfig } from '@/config/types';
import { filterMenu, MenuVisibilityContext } from './menu-filter';

const ctx = (over: Partial<MenuVisibilityContext> = {}): MenuVisibilityContext => ({
  can: () => true,
  isModuleActive: () => true,
  modulesReady: true,
  showPlatform: false,
  ...over,
});

describe('filterMenu', () => {
  it('drops a permission-tagged item the session cannot see', () => {
    const menu: MenuConfig = [
      { title: 'Users', path: '/users', permission: 'users.read' },
      { title: 'Open', path: '/open' },
    ];
    const out = filterMenu(menu, ctx({ can: (k) => k !== 'users.read' }));
    expect(out.map((i) => i.title)).toEqual(['Open']);
  });

  it('keeps a permission-tagged item the session holds', () => {
    const menu: MenuConfig = [
      { title: 'Users', path: '/users', permission: 'users.read' },
    ];
    expect(filterMenu(menu, ctx())).toHaveLength(1);
  });

  it('prunes nested children and drops an emptied parent', () => {
    const menu: MenuConfig = [
      {
        title: 'User Management',
        children: [
          { title: 'Users', path: '/users', permission: 'users.read' },
          { title: 'Roles', path: '/roles', permission: 'roles.read' },
        ],
      },
    ];
    expect(filterMenu(menu, ctx({ can: () => false }))).toEqual([]);
  });

  it('keeps a parent while at least one child survives', () => {
    const menu: MenuConfig = [
      {
        title: 'User Management',
        children: [
          { title: 'Users', path: '/users', permission: 'users.read' },
          { title: 'Roles', path: '/roles', permission: 'roles.read' },
        ],
      },
    ];
    const out = filterMenu(menu, ctx({ can: (k) => k === 'roles.read' }));
    expect(out).toHaveLength(1);
    expect(out[0].children?.map((c) => c.title)).toEqual(['Roles']);
  });

  it('prunes deep (level-2) children up through the chain', () => {
    const menu: MenuConfig = [
      {
        title: 'Root',
        children: [
          {
            title: 'Group',
            children: [
              { title: 'Leaf', path: '/leaf', permission: 'leaf.read' },
            ],
          },
        ],
      },
    ];
    expect(filterMenu(menu, ctx({ can: () => false }))).toEqual([]);
    expect(filterMenu(menu, ctx())).toHaveLength(1);
  });

  it('drops platformOnly items for non-platform sessions', () => {
    const menu: MenuConfig = [
      { title: 'Tenants', path: '/platform/tenants', platformOnly: true },
    ];
    expect(filterMenu(menu, ctx({ showPlatform: false }))).toEqual([]);
    expect(filterMenu(menu, ctx({ showPlatform: true }))).toHaveLength(1);
  });

  it('hides module-tagged items until installed modules are ready', () => {
    const menu: MenuConfig = [
      { title: 'Inbox', path: '/inbox', module: 'omnichannel' },
    ];
    expect(filterMenu(menu, ctx({ modulesReady: false }))).toEqual([]);
    expect(
      filterMenu(menu, ctx({ isModuleActive: (m) => m === 'omnichannel' })),
    ).toHaveLength(1);
    expect(filterMenu(menu, ctx({ isModuleActive: () => false }))).toEqual([]);
  });

  it('combines module + permission gates on one subtree', () => {
    const menu: MenuConfig = [
      {
        title: 'Omnichannel',
        module: 'omnichannel',
        children: [
          { title: 'Inbox', path: '/inbox', permission: 'conversations.read' },
          { title: 'Channels', path: '/channels', permission: 'channels.read' },
        ],
      },
    ];
    // module active but no channel perms → parent survives with one child
    const out = filterMenu(
      menu,
      ctx({ can: (k) => k === 'conversations.read' }),
    );
    expect(out[0].children?.map((c) => c.title)).toEqual(['Inbox']);
    // all child perms missing → parent disappears even though module active
    expect(filterMenu(menu, ctx({ can: () => false }))).toEqual([]);
  });

  it('drops a heading whose entire section was pruned', () => {
    const menu: MenuConfig = [
      { heading: 'Apps' },
      { title: 'Users', path: '/users', permission: 'users.read' },
      { heading: 'Other' },
      { title: 'Open', path: '/open' },
    ];
    const out = filterMenu(menu, ctx({ can: () => false }));
    expect(out.map((i) => i.heading ?? i.title)).toEqual(['Other', 'Open']);
  });

  it('drops a trailing orphan heading', () => {
    const menu: MenuConfig = [
      { title: 'Open', path: '/open' },
      { heading: 'Platform' },
    ];
    const out = filterMenu(menu, ctx());
    expect(out.map((i) => i.heading ?? i.title)).toEqual(['Open']);
  });

  it('does not mutate the source config', () => {
    const menu: MenuConfig = [
      {
        title: 'Parent',
        children: [{ title: 'A', path: '/a', permission: 'a.read' }],
      },
    ];
    const snapshot = JSON.parse(JSON.stringify(menu));
    filterMenu(menu, ctx({ can: () => false }));
    expect(menu).toEqual(snapshot);
  });
});
