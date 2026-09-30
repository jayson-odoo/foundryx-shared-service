import type {
  BuildEvent,
  BuildInfo,
  BusinessRequirementDetail,
} from '@/types/business-requirement';

/** Test fixtures shared by the send-to-build tests (plan ideation-br-send-to-build S0). */
export function buildInfo(over: Partial<BuildInfo> = {}): BuildInfo {
  return {
    canSend: true,
    sendEdgeAvailable: true,
    blockers: [],
    repo: 'jayson-odoo/sorento-crm',
    issueUrl: null,
    issueNumber: null,
    state: 'none',
    sentAt: null,
    sentBy: null,
    stage: null,
    prUrl: null,
    handtestUrl: null,
    events: [],
    ...over,
  };
}

export function buildEvent(over: Partial<BuildEvent> = {}): BuildEvent {
  return {
    id: 'ev-1',
    seq: 1,
    kind: 'crew',
    stage: 'queued',
    message: 'Picked up',
    prUrl: null,
    handtestUrl: null,
    status: null,
    statusMoved: false,
    actorName: null,
    createdAt: '2026-09-30T08:00:00Z',
    ...over,
  };
}

export function brWithBuild(
  build: BuildInfo,
  over: Partial<BusinessRequirementDetail> = {},
): BusinessRequirementDetail {
  return {
    id: 'br-1',
    productId: 'prod-1',
    productName: 'Sorento CRM',
    status: 'ready',
    statusLabel: 'Ready',
    statusColor: 'green',
    templateKey: 'business_requirement',
    templateVersion: 1,
    title: 'Order export',
    ideaCount: 2,
    createdAt: '2026-07-20T10:00:00Z',
    updatedAt: '2026-07-20T10:00:00Z',
    answers: {},
    templateDoc: { schemaVersion: 1, pages: [] },
    build,
    ...over,
  };
}
