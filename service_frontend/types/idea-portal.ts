/**
 * Idea portal wire types (lane IDEA-PORTAL) - mirror of
 * `service_backend/modules/ideation/schemas.py` `Portal*` models.
 */

export type PortalKind = 'staff' | 'crm';

export interface PortalPrincipal {
  kind: PortalKind;
  name: string | null;
  role: string;
  productId: string | null;
  /** May hide ideas, edit changelog notes and delete anyone's comment. */
  canManage: boolean;
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
  productName: string | null;
  submittedAt: string | null;
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
  problem: string | null;
  desiredOutcome: string | null;
  /** One entry per use case. */
  useCases: string[] | null;
  currentWorkaround: string | null;
  submitterFirstName: string | null;
  timeline: PortalTimelineStep[];
  portalHidden: boolean | null;
  note: string | null;
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
  useCases?: string | null;
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
