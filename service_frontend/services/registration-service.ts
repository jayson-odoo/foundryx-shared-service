/**
 * Cluster D (sprint-4/05) registration service — Venues, Zones, Seats,
 * Offerings, CapacityUnits. Talks to the `ems` module routers via the shared
 * api-client (Phase B — the in-memory mock was swapped out once the backend
 * landed; the method boundary is unchanged so no UI touched).
 */
import { apiFetch, publicFetch } from '@/lib/api-client';
import type { ListQuery, ListResult } from '@/types/resource';
import type {
  CapacityUnit,
  Offering,
  OfferingCreate,
  OfferingUpdate,
  PublicEvent,
  SeatGenerateRequest,
  Venue,
  VenueCreate,
  VenueSeat,
  VenueUpdate,
  VenueZone,
  VenueZoneCreate,
  VenueZoneUpdate,
} from '@/types/registration';

interface EmsList<T> {
  items: T[];
  total: number;
  page: number;
  pageSize: number;
}

function venueQuery(q: ListQuery): string {
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

function csvCell(v: unknown): string {
  const s = v == null ? '' : String(v);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

export const registrationService = {
  // ── Venues ──
  async listVenuesQuery(q: ListQuery): Promise<ListResult<Venue>> {
    const p = await apiFetch<EmsList<Venue>>(`/ems/venues?${venueQuery(q)}`);
    return { data: p.items, total: p.total, page: p.page };
  },
  async exportVenues(): Promise<string> {
    // No dedicated export endpoint — build the CSV from a full page (slice-1 scope).
    const p = await apiFetch<EmsList<Venue>>('/ems/venues?page=0&page_size=200');
    const cols: [string, (v: Venue) => unknown][] = [
      ['id', (v) => v.id],
      ['name', (v) => v.name],
      ['address', (v) => v.address ?? ''],
      ['capacity', (v) => v.capacity ?? ''],
      ['zones', (v) => v.zoneCount],
      ['seats', (v) => v.seatCount],
    ];
    const header = cols.map(([c]) => c).join(',');
    const body = p.items.map((v) => cols.map(([, f]) => csvCell(f(v))).join(',')).join('\n');
    return `${header}\n${body}`;
  },
  getVenue(id: string): Promise<Venue> {
    return apiFetch<Venue>(`/ems/venues/${id}`);
  },
  createVenue(body: VenueCreate): Promise<Venue> {
    return apiFetch<Venue>('/ems/venues', { method: 'POST', body: JSON.stringify(body) });
  },
  updateVenue(id: string, body: VenueUpdate): Promise<Venue> {
    return apiFetch<Venue>(`/ems/venues/${id}`, { method: 'PATCH', body: JSON.stringify(body) });
  },
  async deleteVenue(id: string): Promise<void> {
    await apiFetch<void>(`/ems/venues/${id}`, { method: 'DELETE' });
  },

  // ── Zones ──
  listZones(venueId: string): Promise<VenueZone[]> {
    return apiFetch<VenueZone[]>(`/ems/venues/${venueId}/zones`);
  },
  createZone(venueId: string, body: VenueZoneCreate): Promise<VenueZone> {
    return apiFetch<VenueZone>(`/ems/venues/${venueId}/zones`, {
      method: 'POST',
      body: JSON.stringify(body),
    });
  },
  updateZone(zoneId: string, body: VenueZoneUpdate): Promise<VenueZone> {
    return apiFetch<VenueZone>(`/ems/venues/zones/${zoneId}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    });
  },
  async deleteZone(zoneId: string): Promise<void> {
    await apiFetch<void>(`/ems/venues/zones/${zoneId}`, { method: 'DELETE' });
  },

  // ── Seats ──
  listSeats(venueId: string): Promise<VenueSeat[]> {
    return apiFetch<VenueSeat[]>(`/ems/venues/${venueId}/seats`);
  },
  generateSeats(req: SeatGenerateRequest): Promise<VenueSeat[]> {
    return apiFetch<VenueSeat[]>('/ems/venues/seats/generate', {
      method: 'POST',
      body: JSON.stringify(req),
    });
  },
  async clearZoneSeats(zoneId: string): Promise<void> {
    await apiFetch<void>(`/ems/venues/zones/${zoneId}/seats`, { method: 'DELETE' });
  },

  // ── Offerings (per project) ──
  listOfferings(projectId: string): Promise<Offering[]> {
    return apiFetch<Offering[]>(`/ems/projects/${projectId}/offerings`);
  },
  getOffering(projectId: string, offeringId: string): Promise<Offering> {
    return apiFetch<Offering>(`/ems/projects/${projectId}/offerings/${offeringId}`);
  },
  createOffering(projectId: string, body: OfferingCreate): Promise<Offering> {
    return apiFetch<Offering>(`/ems/projects/${projectId}/offerings`, {
      method: 'POST',
      body: JSON.stringify(body),
    });
  },
  updateOffering(projectId: string, offeringId: string, body: OfferingUpdate): Promise<Offering> {
    return apiFetch<Offering>(`/ems/projects/${projectId}/offerings/${offeringId}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    });
  },
  async deleteOffering(projectId: string, offeringId: string): Promise<void> {
    await apiFetch<void>(`/ems/projects/${projectId}/offerings/${offeringId}`, { method: 'DELETE' });
  },

  // ── Capacity minting (RESERVED) ──
  listCapacityUnits(projectId: string, offeringId: string): Promise<CapacityUnit[]> {
    return apiFetch<CapacityUnit[]>(
      `/ems/projects/${projectId}/offerings/${offeringId}/units`,
    );
  },
  mintCapacityUnits(projectId: string, offeringId: string): Promise<CapacityUnit[]> {
    return apiFetch<CapacityUnit[]>(
      `/ems/projects/${projectId}/offerings/${offeringId}/mint`,
      { method: 'POST' },
    );
  },

  // ── Public registration portal (anonymous, read-only — slice 1) ──
  getPublicEvent(tenantSlug: string, projectId: string): Promise<PublicEvent> {
    return publicFetch<PublicEvent>(`/public/register/${tenantSlug}/${projectId}`);
  },
};
