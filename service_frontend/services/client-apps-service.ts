/**
 * Client-apps service - the boundary the Client apps settings screen talks
 * to.
 *
 *   GET   /omnichannel/client-apps                           (partner_keys.manage)
 *   POST  /omnichannel/client-apps                           (partner_keys.manage)
 *   PATCH /omnichannel/client-apps/{id}                       (partner_keys.manage)
 *   POST  /omnichannel/client-apps/{id}/workspaces/move        (partner_keys.manage)
 */
import type { ClientApp, CreateClientAppInput, UpdateClientAppInput } from '@/types/omnichannel';
import { realClientAppsService } from './client-apps-service.real';

export interface ClientAppsService {
  list(): Promise<ClientApp[]>;
  create(input: CreateClientAppInput): Promise<ClientApp>;
  rename(id: string, input: UpdateClientAppInput): Promise<ClientApp>;
  /** Re-points `workspaceId` so it belongs to `targetClientAppId`; returns the target app. */
  moveWorkspace(targetClientAppId: string, workspaceId: string): Promise<ClientApp>;
}

export const clientAppsService: ClientAppsService = realClientAppsService;
