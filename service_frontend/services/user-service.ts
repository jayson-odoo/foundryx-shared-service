/**
 * User service — the boundary the UI talks to (via hooks). Phase A binds the
 * mock implementation; Phase B swaps `userService` to the real api-client impl
 * in ONE line (see bottom of this file). The interface IS the backend contract.
 */
import type { CreateUserInput, UpdateUserInput, User } from '@/types/user';
import type { ListQuery, ListResult } from '@/types/resource';
import { realUserService } from './user-service.real';

export interface UserService {
  list(query: ListQuery): Promise<ListResult<User>>;
  get(id: string): Promise<User>;
  /** Record-nav: the user at `index` within the ordered query, plus the total. */
  getAt(query: ListQuery, index: number): Promise<{ user: User | null; total: number }>;
  create(input: CreateUserInput): Promise<User>;
  update(id: string, input: UpdateUserInput): Promise<User>;
  trash(ids: string[]): Promise<void>;
  restore(ids: string[]): Promise<void>;
  /** (Re)send invitation to eligible (INVITED) users. */
  invite(ids: string[]): Promise<void>;
  resetPassword(id: string): Promise<void>;
  resendVerification(id: string): Promise<void>;
  /** Selected rows if `ids` given, else the whole filtered set. Returns CSV text. */
  exportCsv(query: ListQuery, columns: string[], ids?: string[]): Promise<string>;
}

// Phase B: real api-client implementation. (Mock retained in user-service.mock.ts.)
export const userService: UserService = realUserService;
