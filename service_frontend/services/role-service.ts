/**
 * Role service — the boundary the Roles list + detail form talk to (via hooks).
 * Phase A binds the mock; Phase B swaps `roleService` to the real api-client impl
 * in ONE line (bottom of file). The interface IS the backend contract (plan 03).
 */
import type {
  AssignableUser,
  CreateRoleInput,
  RoleDetail,
  RoleListItem,
  RoleUser,
  UpdateRoleInput,
} from '@/types/role';
import type { ListQuery, ListResult } from '@/types/resource';
import { realRoleService } from './role-service.real';

export interface RoleService {
  list(query: ListQuery): Promise<ListResult<RoleListItem>>;
  get(id: string): Promise<RoleDetail>;
  /** Record-nav: the role at `index` within the ordered query, plus the total. */
  getAt(query: ListQuery, index: number): Promise<{ role: RoleDetail | null; total: number }>;
  create(input: CreateRoleInput): Promise<RoleDetail>;
  update(id: string, input: UpdateRoleInput): Promise<RoleDetail>;
  /** Hard delete (system roles rejected). Cascades user_roles + role_permissions. */
  remove(id: string): Promise<void>;

  /** Users currently holding the role (Assigned Users tab). */
  getAssignedUsers(roleId: string, search?: string): Promise<RoleUser[]>;
  /** Tenant users NOT yet holding the role (the "Assign user" picker). */
  listAssignable(roleId: string, search?: string): Promise<AssignableUser[]>;
  assignUsers(roleId: string, userIds: string[]): Promise<void>;
  removeUser(roleId: string, userId: string): Promise<void>;

  /** Selected rows if `ids` given, else the whole filtered set. Returns CSV text. */
  exportCsv(query: ListQuery, columns: string[], ids?: string[]): Promise<string>;
}

// Phase B: real api-client. (Mock retained in role-service.mock.ts for tests.)
export const roleService: RoleService = realRoleService;
