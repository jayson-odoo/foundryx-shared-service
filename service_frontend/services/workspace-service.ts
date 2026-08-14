/**
 * Workspace service - the boundary the UI talks to (via hooks/configs). Phase A
 * binds the MOCK implementation; Phase B swaps `workspaceService` to the real
 * api-client impl in ONE line (see bottom). The interface IS the backend contract.
 */
import type {
  CreateWorkspaceInput,
  MemberCandidate,
  UpdateWorkspaceInput,
  Workspace,
  WorkspaceMember,
} from '@/types/omnichannel';
import type { ListQuery, ListResult } from '@/types/resource';
import { realWorkspaceService } from './workspace-service.real';

export interface WorkspaceService {
  list(query: ListQuery): Promise<ListResult<Workspace>>;
  get(id: string): Promise<Workspace>;
  /** Record-nav: the workspace at `index` within the ordered query, plus the total. */
  getAt(query: ListQuery, index: number): Promise<{ workspace: Workspace | null; total: number }>;
  create(input: CreateWorkspaceInput): Promise<Workspace>;
  update(id: string, input: UpdateWorkspaceInput): Promise<Workspace>;
  trash(ids: string[]): Promise<void>;
  restore(ids: string[]): Promise<void>;
  /** Members of a workspace (optionally filtered by search). */
  getMembers(workspaceId: string, search?: string): Promise<WorkspaceMember[]>;
  /** Core users not yet members, eligible to be added. */
  listAssignable(workspaceId: string, search?: string): Promise<MemberCandidate[]>;
  /** Add core users as members of the workspace. */
  assignMembers(workspaceId: string, userIds: string[]): Promise<void>;
  /** Remove a member from the workspace. */
  removeMember(workspaceId: string, userId: string): Promise<void>;
  exportCsv(query: ListQuery, columns: string[], ids?: string[]): Promise<string>;
}

// Phase B: real api-client implementation. (Mock retained in *.mock.ts.)
export const workspaceService: WorkspaceService = realWorkspaceService;
