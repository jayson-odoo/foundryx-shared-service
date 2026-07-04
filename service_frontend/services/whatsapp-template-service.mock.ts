/**
 * Mock WhatsApp template service (frontend-first phase + vitest). In-memory
 * dataset across all statuses; the lifecycle mirrors the backend dev stubs
 * (submit→PENDING, sync promotes PENDING→APPROVED, edit→PENDING, delete local).
 */
import type { ListQuery, ListResult } from '@/types/resource';
import type {
  TemplateDetail,
  TemplateManageItem,
  TemplateStatus,
  WaTemplateDoc,
} from '@/types/whatsapp-template';
import { fromMetaComponents, toMetaComponents, validateDoc } from '@/lib/whatsapp-template';
import { delay } from './mock-query';

interface Row extends TemplateManageItem {
  components: Record<string, unknown>[];
}

const EPOCH = Date.parse('2026-06-01T09:00:00Z');
let counter = 0;
function nextId(): string {
  counter += 1;
  return `wtpl-${String(counter).padStart(3, '0')}`;
}

function rowFromDoc(
  channelId: string,
  doc: WaTemplateDoc,
  status: TemplateStatus,
  extra: Partial<Row> = {},
): Row {
  const components = toMetaComponents(doc) as Record<string, unknown>[];
  const bodyPreview = doc.body.text;
  return {
    id: nextId(),
    channelId,
    name: doc.name,
    language: doc.language,
    category: doc.category,
    status,
    quality: null,
    rejectedReason: null,
    bodyPreview,
    variableCount: new Set(Array.from(bodyPreview.matchAll(/\{\{\s*(\d+)\s*\}\}/g)).map((m) => m[1])).size,
    metaTemplateId: null,
    lastSyncedAt: null,
    createdAt: new Date(EPOCH).toISOString(),
    components,
    ...extra,
  };
}

function seed(channelId: string): Row[] {
  const make = (
    name: string,
    category: 'MARKETING' | 'UTILITY',
    bodyText: string,
    examples: string[],
    status: TemplateStatus,
    extra: Partial<Row> = {},
  ) =>
    rowFromDoc(
      channelId,
      { name, category, language: 'en_US', body: { text: bodyText, examples } },
      status,
      extra,
    );
  return [
    make('order_update', 'UTILITY', 'Your order {{1}} is on the way.', ['A123'], 'APPROVED', {
      quality: 'GREEN',
      metaTemplateId: 'mtpl-1',
    }),
    make('event_invite', 'MARKETING', 'You are invited to {{1}}!', ['our gala'], 'REJECTED', {
      rejectedReason: 'INVALID_FORMAT',
      metaTemplateId: 'mtpl-2',
    }),
    make('conversation_follow_up', 'MARKETING', 'Hi {{1}}, can we help further?', ['there'], 'PENDING', {
      metaTemplateId: 'mtpl-3',
    }),
  ];
}

const store: Record<string, Row[]> = {};
function rows(channelId: string): Row[] {
  if (!store[channelId]) store[channelId] = seed(channelId);
  return store[channelId];
}

function toItem(r: Row): TemplateManageItem {
  const item = { ...r } as Partial<Row>;
  delete item.components;
  return item as TemplateManageItem;
}
function toDetail(r: Row): TemplateDetail {
  return {
    ...toItem(r),
    components: r.components,
    doc: fromMetaComponents(r.components, {
      name: r.name,
      category: (r.category as 'MARKETING' | 'UTILITY') || 'UTILITY',
      language: r.language || 'en_US',
    }),
  };
}

export const mockWhatsappTemplateService = {
  async listManage(channelId: string, query: ListQuery): Promise<ListResult<TemplateManageItem>> {
    let list = rows(channelId);
    const extra = (query as ListQuery & { extra?: Record<string, string> }).extra || {};
    if (query.search) list = list.filter((r) => r.name.includes(query.search!.toLowerCase()));
    if (extra.status) list = list.filter((r) => r.status === extra.status);
    if (extra.category) list = list.filter((r) => r.category === extra.category);
    if (extra.language) list = list.filter((r) => r.language === extra.language);
    const total = list.length;
    const start = query.page * query.pageSize;
    return delay({ data: list.slice(start, start + query.pageSize).map(toItem), total, page: query.page });
  },

  async get(channelId: string, templateId: string): Promise<TemplateDetail> {
    const r = rows(channelId).find((x) => x.id === templateId);
    if (!r) throw new Error('Template not found');
    return delay(toDetail(r));
  },

  async saveDraft(channelId: string, doc: WaTemplateDoc): Promise<TemplateDetail> {
    const errors = validateDoc(doc, new Set(rows(channelId).map((r) => r.name)));
    if (Object.keys(errors).length) throw new Error(Object.values(errors)[0]);
    const r = rowFromDoc(channelId, doc, 'LOCAL_DRAFT');
    rows(channelId).unshift(r);
    return delay(toDetail(r));
  },

  async edit(channelId: string, templateId: string, doc: WaTemplateDoc): Promise<TemplateDetail> {
    const r = rows(channelId).find((x) => x.id === templateId);
    if (!r) throw new Error('Template not found');
    if (r.status === 'PENDING' || r.status === 'DISABLED') throw new Error('Cannot edit in this state');
    Object.assign(r, {
      name: doc.name,
      language: doc.language,
      category: doc.category,
      components: toMetaComponents(doc),
      bodyPreview: doc.body.text,
    });
    if (['APPROVED', 'REJECTED', 'PAUSED'].includes(r.status)) {
      r.status = 'PENDING';
      r.rejectedReason = null;
    }
    return delay(toDetail(r));
  },

  async submit(channelId: string, templateId: string): Promise<TemplateDetail> {
    const r = rows(channelId).find((x) => x.id === templateId);
    if (!r) throw new Error('Template not found');
    if (r.status !== 'LOCAL_DRAFT') throw new Error('Only a draft can be submitted');
    r.status = 'PENDING';
    r.metaTemplateId = `mtpl.dev-${r.id}`;
    return delay(toDetail(r));
  },

  async remove(channelId: string, templateId: string): Promise<void> {
    store[channelId] = rows(channelId).filter((r) => r.id !== templateId);
    return delay(undefined);
  },

  async sync(channelId: string): Promise<TemplateManageItem[]> {
    for (const r of rows(channelId)) {
      if (r.status === 'PENDING') {
        r.status = 'APPROVED';
        r.quality = r.quality || 'GREEN';
        r.lastSyncedAt = new Date(EPOCH).toISOString();
      }
    }
    return delay(rows(channelId).map(toItem));
  },

  async uploadSample(channelId: string, file: File) {
    return delay({ sampleKey: `mock-sample:${channelId}:${file.name}`, mime: 'image/png' });
  },
};
