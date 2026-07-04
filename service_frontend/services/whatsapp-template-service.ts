/**
 * WhatsApp template management service (plan 07). UI talks to this boundary;
 * the real impl hits FastAPI, the mock drives the frontend-first phase offline.
 * (Distinct from `template-service.*`, which is the core email Template Engine.)
 */
import type { ListQuery, ListResult } from '@/types/resource';
import type { TemplateDetail, TemplateManageItem, WaTemplateDoc } from '@/types/whatsapp-template';
import { realWhatsappTemplateService } from './whatsapp-template-service.real';

export interface UploadSampleResult {
  sampleKey: string;
  mime: string;
}

export interface WhatsappTemplateService {
  listManage(channelId: string, query: ListQuery): Promise<ListResult<TemplateManageItem>>;
  get(channelId: string, templateId: string): Promise<TemplateDetail>;
  saveDraft(channelId: string, doc: WaTemplateDoc): Promise<TemplateDetail>;
  edit(channelId: string, templateId: string, doc: WaTemplateDoc): Promise<TemplateDetail>;
  submit(channelId: string, templateId: string): Promise<TemplateDetail>;
  remove(channelId: string, templateId: string): Promise<void>;
  sync(channelId: string): Promise<TemplateManageItem[]>;
  uploadSample(channelId: string, file: File): Promise<UploadSampleResult>;
}

export const whatsappTemplateService: WhatsappTemplateService = realWhatsappTemplateService;
