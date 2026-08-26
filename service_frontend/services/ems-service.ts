/** EMS service (sprint-3/11, F4) - profiles / types / templates / events /
 * participants. Talks to the `ems` module routers via the shared api-client. */
import { apiFetch, apiFetchText } from '@/lib/api-client';
import type { ListQuery, ListResult } from '@/types/resource';
import type {
  Checkpoint,
  CheckpointCreate,
  CheckpointLog,
  Client,
  CreatedInvoice,
  EmsList,
  FileLink,
  InvoiceLineSelection,
  Lead,
  LeadEvent,
  NominateResult,
  Participant,
  Product,
  ProductCategory,
  ProductKind,
  Profile,
  Project,
  ProjectTemplate,
  ProjectType,
  ProjectUpdate,
  Quotation,
  SalesOrder,
  ScanResult,
  TemplateChild,
  TenantSettings,
  Ticket,
  VoidRefundResult,
} from '@/types/ems';

/** Map an EMS list page ({items,total,page,pageSize}) → the Resource shell's
 * ListResult ({data,total,page}). */
function toListResult<T>(p: EmsList<T>): ListResult<T> {
  return { data: p.items, total: p.total, page: p.page };
}

function queryParams(q: ListQuery): string {
  const sp = new URLSearchParams();
  sp.set('page', String(q.page));
  sp.set('page_size', String(q.pageSize));
  if (q.search) sp.set('search', q.search);
  if (q.sort) {
    sp.set('sort_by', q.sort.id);
    sp.set('sort_dir', q.sort.desc ? 'desc' : 'asc');
  }
  if (q.statusView === 'trashed') sp.set('trashed', 'true');
  return sp.toString();
}

interface ListParams {
  search?: string;
  page?: number;
  pageSize?: number;
}

function qs(params: Record<string, string | number | boolean | undefined>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== '') sp.set(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : '';
}

export const emsService = {
  // profiles
  listProfiles(p: ListParams = {}) {
    return apiFetch<EmsList<Profile>>(
      `/ems/profiles${qs({ search: p.search, page: p.page ?? 0, page_size: p.pageSize ?? 25 })}`,
    );
  },
  createProfile(body: Partial<Profile>) {
    return apiFetch<Profile>('/ems/profiles', { method: 'POST', body: JSON.stringify(body) });
  },
  getProfile(id: string) {
    return apiFetch<Profile>(`/ems/profiles/${id}`);
  },
  updateProfile(id: string, body: Partial<Profile>) {
    return apiFetch<Profile>(`/ems/profiles/${id}`, { method: 'PATCH', body: JSON.stringify(body) });
  },
  transitionProfile(id: string, toStatusId: string) {
    return apiFetch<Profile>(`/ems/profiles/${id}/transition`, {
      method: 'POST',
      body: JSON.stringify({ toStatusId }),
    });
  },
  transitionProject(id: string, toStatusId: string) {
    return apiFetch<Project>(`/ems/projects/${id}/transition`, {
      method: 'POST',
      body: JSON.stringify({ toStatusId }),
    });
  },
  updateProject(id: string, body: ProjectUpdate) {
    return apiFetch<Project>(`/ems/projects/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    });
  },
  // Resource-shell list + export (id-first CSV → export → edit → re-import).
  async listProfilesQuery(q: ListQuery): Promise<ListResult<Profile>> {
    return toListResult(await apiFetch<EmsList<Profile>>(`/ems/profiles?${queryParams(q)}`));
  },
  exportProfiles(q: ListQuery, columns: string[], ids?: string[]): Promise<string> {
    return apiFetchText('/ems/profiles/export', {
      method: 'POST',
      body: JSON.stringify({ columns, ids, search: q.search ?? null, trashed: q.statusView === 'trashed' }),
    });
  },
  // types
  listTypes(p: ListParams = {}) {
    return apiFetch<EmsList<ProjectType>>(
      `/ems/project-types${qs({ page: p.page ?? 0, page_size: p.pageSize ?? 200 })}`,
    );
  },
  createType(body: { name: string; description?: string }) {
    return apiFetch<ProjectType>('/ems/project-types', { method: 'POST', body: JSON.stringify(body) });
  },
  updateType(id: string, body: { name?: string; description?: string }) {
    return apiFetch<ProjectType>(`/ems/project-types/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    });
  },
  deleteType(id: string) {
    return apiFetch<void>(`/ems/project-types/${id}`, { method: 'DELETE' });
  },
  // templates
  listTemplates(p: ListParams & { typeId?: string } = {}) {
    return apiFetch<EmsList<ProjectTemplate>>(
      `/ems/project-templates${qs({ type_id: p.typeId, page: p.page ?? 0, page_size: p.pageSize ?? 200 })}`,
    );
  },
  createTemplate(body: { typeId: string; name: string; description?: string }) {
    return apiFetch<ProjectTemplate>('/ems/project-templates', { method: 'POST', body: JSON.stringify(body) });
  },
  getTemplate(id: string) {
    return apiFetch<ProjectTemplate>(`/ems/project-templates/${id}`);
  },
  updateTemplate(id: string, body: { name?: string; description?: string }) {
    return apiFetch<ProjectTemplate>(`/ems/project-templates/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    });
  },
  deleteTemplate(id: string) {
    return apiFetch<void>(`/ems/project-templates/${id}`, { method: 'DELETE' });
  },
  // template roles / segments (AC-11-01)
  listRoles(templateId: string) {
    return apiFetch<TemplateChild[]>(`/ems/project-templates/${templateId}/roles`);
  },
  addRole(templateId: string, name: string) {
    return apiFetch<TemplateChild>(`/ems/project-templates/${templateId}/roles`, {
      method: 'POST',
      body: JSON.stringify({ name }),
    });
  },
  deleteRole(templateId: string, roleId: string) {
    return apiFetch<void>(`/ems/project-templates/${templateId}/roles/${roleId}`, { method: 'DELETE' });
  },
  listSegments(templateId: string) {
    return apiFetch<TemplateChild[]>(`/ems/project-templates/${templateId}/segments`);
  },
  addSegment(templateId: string, name: string) {
    return apiFetch<TemplateChild>(`/ems/project-templates/${templateId}/segments`, {
      method: 'POST',
      body: JSON.stringify({ name }),
    });
  },
  deleteSegment(templateId: string, segmentId: string) {
    return apiFetch<void>(`/ems/project-templates/${templateId}/segments/${segmentId}`, { method: 'DELETE' });
  },
  // events (projects)
  listProjects(p: ListParams = {}) {
    return apiFetch<EmsList<Project>>(`/ems/projects${qs({ page: p.page ?? 0, page_size: p.pageSize ?? 25 })}`);
  },
  createProject(body: { templateId: string; title: string; brief?: string }) {
    return apiFetch<Project>('/ems/projects', { method: 'POST', body: JSON.stringify(body) });
  },
  getProject(id: string) {
    return apiFetch<Project>(`/ems/projects/${id}`);
  },
  async listProjectsQuery(q: ListQuery): Promise<ListResult<Project>> {
    return toListResult(await apiFetch<EmsList<Project>>(`/ems/projects?${queryParams(q)}`));
  },
  exportProjects(q: ListQuery, columns: string[], ids?: string[]): Promise<string> {
    return apiFetchText('/ems/projects/export', {
      method: 'POST',
      body: JSON.stringify({ columns, ids, search: q.search ?? null }),
    });
  },
  // participants
  listParticipants(projectId: string, p: ListParams = {}) {
    return apiFetch<EmsList<Participant>>(
      `/ems/projects/${projectId}/participants${qs({ page: p.page ?? 0, page_size: p.pageSize ?? 25 })}`,
    );
  },
  addParticipant(projectId: string, body: { profileId: string; roleId?: string; segmentId?: string }) {
    return apiFetch<Participant>(`/ems/projects/${projectId}/participants`, {
      method: 'POST',
      body: JSON.stringify(body),
    });
  },
  updateParticipant(
    projectId: string,
    participantId: string,
    body: { roleId?: string | null; segmentId?: string | null },
  ) {
    return apiFetch<Participant>(`/ems/projects/${projectId}/participants/${participantId}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    });
  },
  transitionParticipant(projectId: string, participantId: string, toStatusId: string) {
    return apiFetch<Participant>(
      `/ems/projects/${projectId}/participants/${participantId}/transition`,
      { method: 'POST', body: JSON.stringify({ toStatusId }) },
    );
  },
  // ── tickets (Cluster D slice 3) ─────────────────────────────────────────────
  listParticipantTickets(projectId: string, participantId: string) {
    return apiFetch<Ticket[]>(
      `/ems/projects/${projectId}/participants/${participantId}/tickets`,
    );
  },
  nominateTicket(projectId: string, ticketId: string, profileId: string) {
    return apiFetch<NominateResult>(`/ems/projects/${projectId}/tickets/${ticketId}/nominate`, {
      method: 'POST',
      body: JSON.stringify({ profileId }),
    });
  },
  voidTicket(projectId: string, ticketId: string) {
    return apiFetch<VoidRefundResult>(`/ems/projects/${projectId}/tickets/${ticketId}/void`, {
      method: 'POST',
    });
  },
  refundTicket(projectId: string, ticketId: string) {
    return apiFetch<VoidRefundResult>(`/ems/projects/${projectId}/tickets/${ticketId}/refund`, {
      method: 'POST',
    });
  },
  // ── check-in / checkpoints (Cluster D slice 3) ─────────────────────────────
  listCheckpoints(projectId: string) {
    return apiFetch<Checkpoint[]>(`/ems/projects/${projectId}/checkpoints`);
  },
  createCheckpoint(projectId: string, body: CheckpointCreate) {
    return apiFetch<Checkpoint>(`/ems/projects/${projectId}/checkpoints`, {
      method: 'POST',
      body: JSON.stringify(body),
    });
  },
  scanTicket(projectId: string, checkpointId: string, qrToken: string) {
    return apiFetch<ScanResult>(
      `/ems/projects/${projectId}/checkpoints/${checkpointId}/scan`,
      { method: 'POST', body: JSON.stringify({ qrToken }) },
    );
  },
  listCheckpointLogs(projectId: string, checkpointId: string, pageSize = 25) {
    return apiFetch<EmsList<CheckpointLog>>(
      `/ems/projects/${projectId}/checkpoints/${checkpointId}/logs${qs({ page_size: pageSize })}`,
    );
  },
  // ── clients (Cluster B) ────────────────────────────────────────────────────
  async listClientsQuery(q: ListQuery): Promise<ListResult<Client>> {
    return toListResult(await apiFetch<EmsList<Client>>(`/crm/clients?${queryParams(q)}`));
  },
  exportClients(q: ListQuery, columns: string[], ids?: string[]): Promise<string> {
    return apiFetchText('/crm/clients/export', {
      method: 'POST',
      body: JSON.stringify({ columns, ids, search: q.search ?? null, trashed: q.statusView === 'trashed' }),
    });
  },
  clientOptions(search?: string) {
    return apiFetch<Client[]>(`/crm/clients/options${qs({ search })}`);
  },
  createClient(body: Partial<Client>) {
    return apiFetch<Client>('/crm/clients', { method: 'POST', body: JSON.stringify(body) });
  },
  getClient(id: string) {
    return apiFetch<Client>(`/crm/clients/${id}`);
  },
  updateClient(id: string, body: Partial<Client>) {
    return apiFetch<Client>(`/crm/clients/${id}`, { method: 'PATCH', body: JSON.stringify(body) });
  },
  transitionClient(id: string, toStatusId: string) {
    return apiFetch<Client>(`/crm/clients/${id}/transition`, {
      method: 'POST',
      body: JSON.stringify({ toStatusId }),
    });
  },
  // ── leads (Cluster B) ──────────────────────────────────────────────────────
  async listLeadsQuery(q: ListQuery, clientId?: string): Promise<ListResult<Lead>> {
    const cid = clientId ? `&clientId=${encodeURIComponent(clientId)}` : '';
    return toListResult(await apiFetch<EmsList<Lead>>(`/crm/leads?${queryParams(q)}${cid}`));
  },
  exportLeads(q: ListQuery, columns: string[], ids?: string[]): Promise<string> {
    return apiFetchText('/crm/leads/export', {
      method: 'POST',
      body: JSON.stringify({ columns, ids, search: q.search ?? null, trashed: q.statusView === 'trashed' }),
    });
  },
  createLead(body: Partial<Lead>) {
    return apiFetch<Lead>('/crm/leads', { method: 'POST', body: JSON.stringify(body) });
  },
  getLead(id: string) {
    return apiFetch<Lead>(`/crm/leads/${id}`);
  },
  updateLead(id: string, body: Partial<Lead>) {
    return apiFetch<Lead>(`/crm/leads/${id}`, { method: 'PATCH', body: JSON.stringify(body) });
  },
  transitionLead(id: string, toStatusId: string) {
    return apiFetch<Lead>(`/crm/leads/${id}/transition`, {
      method: 'POST',
      body: JSON.stringify({ toStatusId }),
    });
  },
  /** Won lead → spawn an event (EMS project) from a template. Repeatable; needs
   *  the Events module installed (else 409). */
  createEventFromLead(id: string, body: { templateId: string; title?: string }) {
    return apiFetch<LeadEvent>(`/crm/leads/${id}/create-event`, {
      method: 'POST',
      body: JSON.stringify(body),
    });
  },
  /** Events spawned from a lead (cross-module; empty when Events not installed). */
  leadEvents(id: string) {
    return apiFetch<LeadEvent[]>(`/crm/leads/${id}/events`);
  },
  // ── product categories (Cluster B) ─────────────────────────────────────────
  listCategories() {
    return apiFetch<ProductCategory[]>('/product-categories');
  },
  getCategory(id: string) {
    return apiFetch<ProductCategory>(`/product-categories/${id}`);
  },
  createCategory(body: { name: string; parentId?: string | null; sort?: number }) {
    return apiFetch<ProductCategory>('/product-categories', {
      method: 'POST',
      body: JSON.stringify(body),
    });
  },
  updateCategory(id: string, body: { name?: string; parentId?: string | null; sort?: number }) {
    return apiFetch<ProductCategory>(`/product-categories/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    });
  },
  deleteCategory(id: string) {
    return apiFetch<void>(`/product-categories/${id}`, { method: 'DELETE' });
  },
  // ── products (Cluster B) ───────────────────────────────────────────────────
  async listProductsQuery(q: ListQuery): Promise<ListResult<Product>> {
    return toListResult(await apiFetch<EmsList<Product>>(`/products?${queryParams(q)}`));
  },
  exportProducts(q: ListQuery, columns: string[], ids?: string[]): Promise<string> {
    return apiFetchText('/products/export', {
      method: 'POST',
      body: JSON.stringify({ columns, ids, search: q.search ?? null, trashed: q.statusView === 'trashed' }),
    });
  },
  productOptions(search?: string) {
    return apiFetch<Product[]>(`/products/options${qs({ search })}`);
  },
  createProduct(body: Partial<Product>) {
    return apiFetch<Product>('/products', { method: 'POST', body: JSON.stringify(body) });
  },
  getProduct(id: string) {
    return apiFetch<Product>(`/products/${id}`);
  },
  updateProduct(id: string, body: Partial<Product>) {
    return apiFetch<Product>(`/products/${id}`, { method: 'PATCH', body: JSON.stringify(body) });
  },
  // ── quotations (Cluster B) ─────────────────────────────────────────────────
  async listQuotationsQuery(q: ListQuery, clientId?: string): Promise<ListResult<Quotation>> {
    const cid = clientId ? `&clientId=${encodeURIComponent(clientId)}` : '';
    return toListResult(await apiFetch<EmsList<Quotation>>(`/crm/quotations?${queryParams(q)}${cid}`));
  },
  /** Full revision lineage of a quotation (oldest→newest). */
  quotationRevisions(id: string) {
    return apiFetch<Quotation[]>(`/crm/quotations/${id}/revisions`);
  },
  exportQuotations(q: ListQuery, columns: string[], ids?: string[]): Promise<string> {
    return apiFetchText('/crm/quotations/export', {
      method: 'POST',
      body: JSON.stringify({ columns, ids, search: q.search ?? null, trashed: q.statusView === 'trashed' }),
    });
  },
  createQuotation(body: Partial<Quotation>) {
    return apiFetch<Quotation>('/crm/quotations', { method: 'POST', body: JSON.stringify(body) });
  },
  getQuotation(id: string) {
    return apiFetch<Quotation>(`/crm/quotations/${id}`);
  },
  updateQuotation(id: string, body: Partial<Quotation>) {
    return apiFetch<Quotation>(`/crm/quotations/${id}`, { method: 'PATCH', body: JSON.stringify(body) });
  },
  transitionQuotation(id: string, toStatusId: string) {
    return apiFetch<Quotation>(`/crm/quotations/${id}/transition`, {
      method: 'POST',
      body: JSON.stringify({ toStatusId }),
    });
  },
  reviseQuotation(id: string) {
    return apiFetch<Quotation>(`/crm/quotations/${id}/revise`, { method: 'POST' });
  },
  // ── sales orders (Cluster F slice 2) ───────────────────────────────────────
  async listSalesOrdersQuery(q: ListQuery, clientId?: string): Promise<ListResult<SalesOrder>> {
    const cid = clientId ? `&clientId=${encodeURIComponent(clientId)}` : '';
    return toListResult(await apiFetch<EmsList<SalesOrder>>(`/crm/sales-orders?${queryParams(q)}${cid}`));
  },
  exportSalesOrders(q: ListQuery, columns: string[], ids?: string[]): Promise<string> {
    return apiFetchText('/crm/sales-orders/export', {
      method: 'POST',
      body: JSON.stringify({ columns, ids, search: q.search ?? null, trashed: q.statusView === 'trashed' }),
    });
  },
  createSalesOrder(body: Partial<SalesOrder>) {
    return apiFetch<SalesOrder>('/crm/sales-orders', { method: 'POST', body: JSON.stringify(body) });
  },
  createSalesOrderFromQuotation(quotationId: string) {
    return apiFetch<SalesOrder>('/crm/sales-orders/from-quotation', {
      method: 'POST',
      body: JSON.stringify({ quotationId }),
    });
  },
  getSalesOrder(id: string) {
    return apiFetch<SalesOrder>(`/crm/sales-orders/${id}`);
  },
  updateSalesOrder(id: string, body: Partial<SalesOrder>) {
    return apiFetch<SalesOrder>(`/crm/sales-orders/${id}`, { method: 'PATCH', body: JSON.stringify(body) });
  },
  transitionSalesOrder(id: string, toStatusId: string) {
    return apiFetch<SalesOrder>(`/crm/sales-orders/${id}/transition`, {
      method: 'POST',
      body: JSON.stringify({ toStatusId }),
    });
  },
  createInvoiceFromSalesOrder(id: string, selections: InvoiceLineSelection[]) {
    return apiFetch<CreatedInvoice>(`/crm/sales-orders/${id}/create-invoice`, {
      method: 'POST',
      body: JSON.stringify({ selections }),
    });
  },
  // ── core catalog extras (sprint-4/08) ──────────────────────────────────────
  productKinds() {
    return apiFetch<ProductKind[]>('/products/kinds');
  },
  getTenantSettings() {
    return apiFetch<TenantSettings>('/settings/general');
  },
  setTenantSettings(body: Partial<TenantSettings>) {
    return apiFetch<TenantSettings>('/settings/general', { method: 'PUT', body: JSON.stringify(body) });
  },
  // ── document attach seam (core /documents/file-links) ──────────────────────
  listFileLinks(entityType: string, entityId: string) {
    return apiFetch<FileLink[]>(
      `/documents/file-links${qs({ entity_type: entityType, entity_id: entityId })}`,
    );
  },
  attachFile(entityType: string, entityId: string, fileId: string) {
    return apiFetch<FileLink>('/documents/file-links', {
      method: 'POST',
      body: JSON.stringify({ entityType, entityId, fileId }),
    });
  },
  detachFile(linkId: string) {
    return apiFetch<void>(`/documents/file-links/${linkId}`, { method: 'DELETE' });
  },
};
