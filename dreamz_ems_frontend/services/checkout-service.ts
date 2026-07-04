/**
 * Public checkout service — Cluster D slice 2 (sprint-4/05). REAL `publicFetch`
 * to the ems public cart/checkout endpoints (anonymous; tenant slug in path).
 * A cart is created lazily on the first hold/qty action and its id cached per
 * (slug, projectId) for the page's lifetime — so the page's method signatures are
 * unchanged from the mock (mock → real was a service-only swap). Confirm clears
 * the cached cart (converted).
 */
import { publicFetch } from '@/lib/api-client';
import type { AllocationMode, AttendeeInput, Cart, CheckoutSeat, OrderResult } from '@/types/registration';

export interface CheckoutOffering {
  id: string;
  productName: string;
  allocationMode: AllocationMode;
  price: number;
  currency: string;
  taxRate: number;
  remaining: number;
  hasSeatMap: boolean;
}
export interface SeatRow {
  row: string;
  seats: CheckoutSeat[];
}

const base = (slug: string, projectId: string) => `/public/register/${slug}/${projectId}`;
const carts = new Map<string, string>(); // `${slug}:${projectId}` → cartId

async function ensureCart(slug: string, projectId: string): Promise<string> {
  const key = `${slug}:${projectId}`;
  const cached = carts.get(key);
  if (cached) return cached;
  const { cartId } = await publicFetch<{ cartId: string }>(`${base(slug, projectId)}/cart`, { method: 'POST' });
  carts.set(key, cartId);
  return cartId;
}

const emptyCart: Cart = { id: '', lines: [], subtotal: 0, tax: 0, total: 0, currency: '', expiresAt: null };

export const checkoutService = {
  getCheckout(slug: string, projectId: string) {
    return publicFetch<{ title: string; currency: string; offerings: CheckoutOffering[] }>(
      `${base(slug, projectId)}/checkout`,
    );
  },

  async getSeatMap(slug: string, projectId: string, offeringId: string): Promise<SeatRow[]> {
    const cartId = await ensureCart(slug, projectId);
    return publicFetch<SeatRow[]>(`${base(slug, projectId)}/seatmap/${offeringId}?cart=${cartId}`);
  },

  async setGaQty(slug: string, projectId: string, offeringId: string, qty: number): Promise<Cart> {
    const cartId = await ensureCart(slug, projectId);
    return publicFetch<Cart>(`${base(slug, projectId)}/cart/${cartId}/ga`, {
      method: 'POST',
      body: JSON.stringify({ offeringId, qty }),
    });
  },

  async toggleSeat(slug: string, projectId: string, offeringId: string, seatId: string): Promise<Cart> {
    const cartId = await ensureCart(slug, projectId);
    return publicFetch<Cart>(`${base(slug, projectId)}/cart/${cartId}/seat`, {
      method: 'POST',
      body: JSON.stringify({ offeringId, seatId }),
    });
  },

  async getCart(slug: string, projectId: string): Promise<Cart> {
    const cartId = carts.get(`${slug}:${projectId}`);
    if (!cartId) return emptyCart;
    return publicFetch<Cart>(`${base(slug, projectId)}/cart/${cartId}`);
  },

  async confirm(slug: string, projectId: string, attendees: AttendeeInput[]): Promise<OrderResult> {
    const cartId = await ensureCart(slug, projectId);
    const order = await publicFetch<{
      orderRef: string;
      invoiceId: string | null;
      total: number;
      currency: string;
      ticketCount: number;
      confirmationEmails: string[];
      tickets?: {
        ticketId: string;
        qrToken: string | null;
        attendeeName: string | null;
        offeringName: string | null;
      }[];
    }>(`${base(slug, projectId)}/cart/${cartId}/confirm`, {
      method: 'POST',
      body: JSON.stringify({ attendees }),
    });
    carts.delete(`${slug}:${projectId}`); // cart converted
    return {
      orderRef: order.orderRef,
      invoiceTotal: order.total,
      currency: order.currency,
      ticketCount: order.ticketCount,
      confirmationEmails: order.confirmationEmails,
      paid: false,
      tickets: order.tickets ?? [],
    };
  },
};
