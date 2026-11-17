/**
 * Idea portal wire types (lane IDEA-PORTAL) - mirror of
 * `service_backend/modules/ideation/schemas.py` `Portal*` models.
 */
import type { IdeaAttachment } from '@/types/ideation';

/** `contact` = a dealer on a personal feedback link (lane PUBLIC-IDEAS-BOARD). */
/** `share` = anyone on one item's read-only share link (lane FEEDBACK-SUBSCRIBE). */
export type PortalKind = 'staff' | 'crm' | 'contact' | 'share';

/** A product's look on its feedback board (lane SS-MULTI-PRODUCT-BOARD). */
export interface PortalBrand {
  name: string | null;
  color: string | null;
}

export interface PortalPrincipal {
  kind: PortalKind;
  name: string | null;
  role: string;
  /** Set when the board is scoped to one product: only that product shows. */
  productId: string | null;
  /** May hide ideas, edit changelog notes and delete anyone's comment. */
  canManage: boolean;
  /** The product's board colour + name; null/absent = the default look. */
  brand?: PortalBrand | null;
}

export interface PortalSession {
  token: string;
  principal: PortalPrincipal;
}

export interface PortalCard {
  id: string;
  ideaNumber: string | null;
  title: string;
  upvotes: number;
  commentCount: number;
  isMine: boolean;
  myVote: boolean;
  column: string | null;
  statusLabel: string | null;
  statusColor: string | null;
  /** Omitted (not null) on another dealer's item for a contact viewer (owner ruling (b)). */
  productName?: string | null;
  submittedAt?: string | null;
}

export interface PortalColumn {
  key: string;
  title: string;
  color: string;
  /** All visible ideas in the column; `ideas` holds the top 100 by votes. */
  count: number;
  ideas: PortalCard[];
}

export interface PortalRoadmap {
  columns: PortalColumn[];
}

export interface PortalList {
  items: PortalCard[];
  total: number;
  page: number;
  pageSize: number;
}

export interface PortalChangelogItem extends PortalCard {
  deliveredAt: string;
  note: string | null;
}

export interface PortalTimelineStep {
  key: string;
  label: string;
  color: string;
  state: 'done' | 'current' | 'upcoming';
}

export interface PortalIdea extends PortalCard {
  /** The free text + submitter keys are omitted on another dealer's item for a
   * contact viewer (owner ruling (b)); present for everyone else. */
  problem?: string | null;
  desiredOutcome?: string | null;
  /** One entry per use case. */
  useCases?: string[] | null;
  currentWorkaround?: string | null;
  submitterFirstName?: string | null;
  timeline: PortalTimelineStep[];
  portalHidden: boolean | null;
  note: string | null;
  /** Lane FEEDBACK-SUBSCRIBE: contacts following it (the submitter not counted). */
  followerCount?: number;
  /** This viewer gets its WhatsApp status updates (submitter or follower). */
  following?: boolean;
  /** Report-level files (comment files ride their comment). Omitted for a
   * contact viewer on another dealer's item, like the free text. */
  attachments?: IdeaAttachment[];
}

export interface PortalFollow {
  following: boolean;
  followerCount: number;
}

export interface PortalShareLink {
  url: string;
}

/** Proven phone on a share link: the visitor's own session + personal board link. */
export interface PortalPhoneSession extends PortalSession {
  boardUrl: string | null;
}

export interface PortalVote {
  id: string;
  upvotes: number;
  myVote: boolean;
}

export interface PortalVoter {
  name: string | null;
  role: string;
  isMe: boolean;
}

export interface PortalComment {
  id: string;
  ideaId: string;
  parentId: string | null;
  authorName: string | null;
  authorKind: string;
  authorRole: string;
  body: string | null;
  isDeleted: boolean;
  isMine: boolean;
  canEdit: boolean;
  canDelete: boolean;
  createdAt: string;
  editedAt: string | null;
  likeCount: number;
  likedByMe: boolean;
  attachments?: IdeaAttachment[];
}

export interface PortalLike {
  likeCount: number;
  likedByMe: boolean;
}

export type PortalActivityKind =
  | 'submitted'
  | 'status_changed'
  | 'comment'
  | 'upvote'
  | 'comment_like';

export interface PortalActivity {
  kind: PortalActivityKind;
  at: string;
  by: string | null;
  source: string | null;
  fromLabel: string | null;
  toLabel: string | null;
  toColor: string | null;
  comment: PortalComment | null;
  replies: PortalComment[];
  commentId: string | null;
}

export interface PortalProduct {
  id: string;
  name: string;
}

export interface PortalIdeaInput {
  title: string;
  problem: string;
  productId: string | null;
  desiredOutcome?: string | null;
  useCases?: string[] | null;
  currentWorkaround?: string | null;
}

export interface PortalListQuery {
  q?: string;
  columns?: string[];
  sort?: 'top' | 'new';
  mine?: boolean;
  productId?: string | null;
  includeClosed?: boolean;
  page?: number;
  pageSize?: number;
}
