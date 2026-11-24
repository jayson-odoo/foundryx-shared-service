import type {
  ClientApp,
  CreateClientAppInput,
  UpdateClientAppInput,
} from '@/types/omnichannel';
import type { ClientAppsService } from './client-apps-service';
import { delay } from './mock-query';

function seed(): ClientApp[] {
  return [
    {
      id: 'app-general',
      name: 'General',
      slug: null,
      status: 'ACTIVE',
      isDefault: true,
      workspaceCount: 1,
      workspaces: [{ id: 'ws-general', name: 'General', isDefault: true }],
    },
    {
      id: 'app-ecohub',
      name: 'Ecohub',
      slug: null,
      status: 'ACTIVE',
      isDefault: false,
      workspaceCount: 1,
      workspaces: [{ id: 'ws-ecohub', name: 'Ecohub', isDefault: false }],
    },
  ];
}

let apps: ClientApp[] = seed();

export function __mockResetClientApps(): void {
  apps = seed();
}

function sameName(a: string, b: string): boolean {
  return a.trim().toLowerCase() === b.trim().toLowerCase();
}

export const mockClientAppsService: ClientAppsService = {
  async list() {
    return delay(apps.map((a) => ({ ...a, workspaces: [...a.workspaces] })));
  },

  async create(input: CreateClientAppInput) {
    const name = input.name.trim();
    if (!name) throw new Error('Name is required.');
    if (apps.some((a) => sameName(a.name, name))) {
      throw new Error('A client app with this name already exists.');
    }
    const app: ClientApp = {
      id: `app-${Date.now()}`,
      name,
      slug: null,
      status: 'ACTIVE',
      isDefault: false,
      workspaceCount: 0,
      workspaces: [],
    };
    apps = [...apps, app];
    return delay({ ...app });
  },

  async rename(id, input: UpdateClientAppInput) {
    const name = input.name.trim();
    if (!name) throw new Error('Name is required.');
    const app = apps.find((a) => a.id === id);
    if (!app) throw new Error('Client app not found.');
    if (apps.some((a) => a.id !== id && sameName(a.name, name))) {
      throw new Error('A client app with this name already exists.');
    }
    app.name = name;
    return delay({ ...app });
  },

  async moveWorkspace(targetClientAppId, workspaceId) {
    const target = apps.find((a) => a.id === targetClientAppId);
    if (!target) throw new Error('Client app not found.');
    let moved: ClientApp['workspaces'][number] | undefined;
    for (const app of apps) {
      const idx = app.workspaces.findIndex((w) => w.id === workspaceId);
      if (idx !== -1) {
        [moved] = app.workspaces.splice(idx, 1);
        app.workspaceCount = app.workspaces.length;
        break;
      }
    }
    if (!moved) throw new Error('Workspace not found.');
    target.workspaces = [...target.workspaces, moved];
    target.workspaceCount = target.workspaces.length;
    return delay({ ...target, workspaces: [...target.workspaces] });
  },
};
