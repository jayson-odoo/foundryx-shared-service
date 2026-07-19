/**
 * Product catalog service — the boundary the Products UI talks to (via the
 * list config + form dialog). Enforced layering:
 *   UI → hooks/config → this service → lib/api-client → FastAPI.
 *
 * ── Backend contract (matched byte-for-byte) ────────────────────────────────
 * Core catalog (service_backend/app/api/v1/catalog.py, schemas/catalog.py):
 *   GET    /products
 *     query: page (0-based, ge=0), page_size (1..200), search, trashed (bool),
 *            sort_by, sort_dir ('asc'|'desc')
 *     → ListResponse { items: ProductOut[], total, page, pageSize }
 *   GET    /products/kinds            → ProductKindOut[] { key, label }
 *                                       (software only lists when Ideation is
 *                                        installed for the tenant)
 *   POST   /products                  body ProductIn  → ProductOut (201)
 *   GET    /products/{id}             → ProductOut
 *   PATCH  /products/{id}             body ProductPatch (partial) → ProductOut
 *   DELETE /products/{id}            → 204 (hard delete)
 *   POST   /products/export          body ExportRequest { columns, ids?, search?,
 *                                       trashed } → text/csv
 *   Permissions: products.read / products.create / products.update /
 *                products.delete
 *
 *   ProductOut  { id, categoryId, name, sku, kind, kindLabel, defaultPrice, tax,
 *                 currency, uom, isActive, createdAt }   (money as float)
 *   ProductIn   { name, kind (default 'service'), categoryId?, sku?, defaultPrice?,
 *                 tax?, currency?, uom?, isActive (default true) }
 *   ProductPatch: every field optional.
 *
 * Ideation delivery extension (service_backend/modules/ideation/routers/products.py,
 * mounted at prefix '/ideation/products'; permission ideation.products.manage):
 *   GET /ideation/products/{id}/delivery → DeliveryConfigOut
 *   PUT /ideation/products/{id}/delivery body DeliveryConfigIn { productDomainBase }
 *                                        → DeliveryConfigOut
 *   DeliveryConfigOut { productId, productDomainBase, createdAt?, updatedAt? }
 *   Only software products carry a delivery row; product_domain_base is the
 *   absolute origin (e.g. https://fe-sorento.foundryx.my) used to mint ideation
 *   idea links. Null until a Maintainer sets it.
 * ────────────────────────────────────────────────────────────────────────────
 */
import { apiFetch, apiFetchText } from '@/lib/api-client';
import type { ListQuery, ListResult } from '@/types/resource';

/** One catalog product (core ProductOut). Money is a float on the wire. */
export interface Product {
  id: string;
  categoryId: string | null;
  name: string;
  sku: string | null;
  kind: string;
  kindLabel: string | null;
  defaultPrice: number | null;
  tax: number | null;
  currency: string | null;
  uom: string | null;
  isActive: boolean;
  createdAt: string;
}

/** A selectable product kind (goods | service | software | tenant customs). */
export interface ProductKind {
  key: string;
  label: string;
}

/** Create payload (core ProductIn). `kind` defaults to 'service' server-side. */
export interface ProductCreateInput {
  name: string;
  kind: string;
  categoryId?: string | null;
  sku?: string | null;
  defaultPrice?: number | null;
  tax?: number | null;
  currency?: string | null;
  uom?: string | null;
  isActive?: boolean;
}

/** Partial update payload (core ProductPatch). */
export type ProductUpdateInput = Partial<ProductCreateInput>;

/** A software product's delivery config (ideation DeliveryConfigOut). */
export interface DeliveryConfig {
  productId: string;
  productDomainBase: string | null;
  createdAt?: string | null;
  updatedAt?: string | null;
}

/** Core list envelope (app/schemas/catalog.py → ListResponse). */
interface ProductListResponse {
  items: Product[];
  total: number;
  page: number;
  pageSize: number;
}

/** Map the FE ListQuery to the core catalog query string. */
function listParams(query: ListQuery): URLSearchParams {
  const p = new URLSearchParams();
  p.set('page', String(query.page));
  p.set('page_size', String(query.pageSize));
  if (query.search) p.set('search', query.search);
  // Core uses a `trashed` bool, not a status_view enum.
  if (query.statusView === 'trashed') p.set('trashed', 'true');
  if (query.sort) {
    p.set('sort_by', query.sort.id);
    p.set('sort_dir', query.sort.desc ? 'desc' : 'asc');
  }
  return p;
}

const productPath = (id: string) => `/products/${encodeURIComponent(id)}`;
const deliveryPath = (id: string) =>
  `/ideation/products/${encodeURIComponent(id)}/delivery`;

export interface ProductService {
  /** Paged list; maps the core `items` envelope onto the ResourceList shape. */
  listProducts(query: ListQuery): Promise<ListResult<Product>>;
  getProduct(id: string): Promise<Product>;
  createProduct(input: ProductCreateInput): Promise<Product>;
  updateProduct(id: string, input: ProductUpdateInput): Promise<Product>;
  /** Hard delete (204). */
  deleteProduct(id: string): Promise<void>;
  /** Selectable kinds (software appears only when Ideation is installed). */
  listKinds(): Promise<ProductKind[]>;
  /** CSV export of the (filtered/selected) set. */
  exportCsv(query: ListQuery, columns: string[], ids?: string[]): Promise<string>;
  /** Read a software product's delivery config (ideation.products.manage). */
  getDelivery(productId: string): Promise<DeliveryConfig>;
  /** Set a software product's product-domain base (ideation.products.manage). */
  setDelivery(
    productId: string,
    body: { productDomainBase: string },
  ): Promise<DeliveryConfig>;
}

export const productService: ProductService = {
  async listProducts(query) {
    const res = await apiFetch<ProductListResponse>(
      `/products?${listParams(query).toString()}`,
    );
    return { data: res.items, total: res.total, page: res.page };
  },

  getProduct(id) {
    return apiFetch<Product>(productPath(id));
  },

  createProduct(input) {
    return apiFetch<Product>('/products', {
      method: 'POST',
      body: JSON.stringify(input),
    });
  },

  updateProduct(id, input) {
    return apiFetch<Product>(productPath(id), {
      method: 'PATCH',
      body: JSON.stringify(input),
    });
  },

  async deleteProduct(id) {
    await apiFetch<void>(productPath(id), { method: 'DELETE' });
  },

  listKinds() {
    return apiFetch<ProductKind[]>('/products/kinds');
  },

  exportCsv(query, columns, ids) {
    return apiFetchText('/products/export', {
      method: 'POST',
      body: JSON.stringify({
        columns,
        ids,
        search: query.search,
        trashed: query.statusView === 'trashed',
      }),
    });
  },

  getDelivery(productId) {
    return apiFetch<DeliveryConfig>(deliveryPath(productId));
  },

  setDelivery(productId, body) {
    return apiFetch<DeliveryConfig>(deliveryPath(productId), {
      method: 'PUT',
      body: JSON.stringify(body),
    });
  },
};
