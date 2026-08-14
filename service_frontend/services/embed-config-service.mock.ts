/**
 * PHASE 1 MOCK - in-memory embed-access config (plan 11H). Retained for Vitest +
 * tunable frontend states; the shipped screen binds the REAL service. Mirrors
 * the backend origin validation so the builder feels real without a backend.
 */
import { validateEmbedOrigin } from '@/lib/embed-origin';
import type {
  EmbedConfig,
  EmbedConfigService,
  EmbedRotateSecretResult,
} from './embed-config-service';

interface MockState {
  connectionId: string | null;
  allowedOrigins: string[];
  hasSecret: boolean;
}

function makeState(): MockState {
  return { connectionId: null, allowedOrigins: [], hasSecret: false };
}

let state: MockState = makeState();

const HOST = 'https://foundryx.example';
const WORKSPACES = [
  { id: 'ws-general', name: 'General' },
  { id: 'ws-sales', name: 'Sales' },
];

function snapshot(): EmbedConfig {
  return {
    connectionId: state.connectionId,
    allowedOrigins: [...state.allowedOrigins],
    hasSecret: state.hasSecret,
    host: HOST,
    workspaces: WORKSPACES.map((w) => ({ ...w })),
  };
}

export const mockEmbedConfigService: EmbedConfigService = {
  async get() {
    return snapshot();
  },
  async enable() {
    if (!state.connectionId) state.connectionId = 'conn-embed-mock-123';
    return snapshot();
  },
  async rotateSecret(): Promise<EmbedRotateSecretResult> {
    if (!state.connectionId) throw new Error('Enable embed access first.');
    state.hasSecret = true;
    return { embedSecret: `emb_mock_${Math.random().toString(36).slice(2, 30)}` };
  },
  async setOrigins(allowedOrigins: string[]) {
    if (!state.connectionId) throw new Error('Enable embed access first.');
    const seen = new Set<string>();
    const clean: string[] = [];
    for (const raw of allowedOrigins) {
      const check = validateEmbedOrigin(raw);
      if (!check.ok || !check.value) throw new Error(check.error ?? 'Invalid origin.');
      if (!seen.has(check.value)) {
        seen.add(check.value);
        clean.push(check.value);
      }
    }
    state.allowedOrigins = clean;
    return snapshot();
  },
};

/** Test hook - reset the in-memory state between cases. */
export function __resetMockEmbedConfig(): void {
  state = makeState();
}
