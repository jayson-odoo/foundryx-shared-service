'use client';

/** Public registration portal — Cluster D slice 2 (sprint-4/05). Anonymous flow
 * on the REAL checkout-service: pick tickets (GA qty / reserved seats on a cinema
 * map, DB-locked holds + countdown) → attendee details → review → payment (card
 * step is mock; gateway = Cluster F) → done (tickets + invoice). Confirm reserves
 * + mints a Draft invoice via the finance capability. Branded by the public
 * layout. Responsive ≤375px. */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useParams } from 'next/navigation';
import { toast } from 'sonner';
import { Armchair, Check, Clock, CreditCard, Loader2, Minus, Plus, Ticket } from 'lucide-react';
import { QRCodeSVG } from 'qrcode.react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { checkoutService, type CheckoutOffering, type SeatRow } from '@/services/checkout-service';
import { eventBillingService } from '@/services/event-billing-service';
import { formatMoney } from '@/lib/money';
import { cn } from '@/lib/utils';
import type { AttendeeInput, Cart, PortalOrder } from '@/types/registration';

type Step = 'tickets' | 'details' | 'review' | 'payment' | 'done';

export default function PublicRegisterPage() {
  const { slug, projectId } = useParams<{ slug: string; projectId: string }>();
  const [loading, setLoading] = useState(true);
  const [title, setTitle] = useState('');
  const [offerings, setOfferings] = useState<CheckoutOffering[]>([]);
  const [cart, setCart] = useState<Cart | null>(null);
  const [step, setStep] = useState<Step>('tickets');
  const [paid, setPaid] = useState(false);

  const refreshCart = useCallback(
    () => checkoutService.getCart(slug, projectId).then(setCart),
    [slug, projectId],
  );

  useEffect(() => {
    checkoutService
      .getCheckout(slug, projectId)
      .then((d) => {
        setTitle(d.title);
        setOfferings(d.offerings);
      })
      .then(refreshCart)
      .finally(() => setLoading(false));
  }, [slug, projectId, refreshCart]);

  const itemCount = cart?.lines.reduce((n, l) => n + l.qty, 0) ?? 0;

  if (loading) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center text-muted-foreground">
        <Loader2 className="size-6 animate-spin" />
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-5xl px-4 py-8 sm:py-12">
      <header className="mb-6">
        <h1 className="font-heading text-2xl font-semibold sm:text-3xl">{title}</h1>
        <Steps step={step} />
      </header>

      <div className="grid gap-6 lg:grid-cols-[1fr_320px]">
        <div className="min-w-0">
          {step === 'tickets' && (
            <TicketsStep slug={slug} projectId={projectId} offerings={offerings} cart={cart} onChange={refreshCart} />
          )}
          {step === 'details' && cart && (
            <DetailsStep cart={cart} onBack={() => setStep('tickets')} onNext={() => setStep('review')} attendeesRef={attendeesStore} />
          )}
          {step === 'review' && cart && (
            <ReviewStep slug={slug} projectId={projectId} cart={cart} onBack={() => setStep('details')} onReserved={() => { setStep('payment'); refreshCart(); }} />
          )}
          {step === 'payment' && (
            <PaymentStep
              onPaid={() => { setPaid(true); setStep('done'); }}
              onPayLater={() => { setPaid(false); setStep('done'); }}
            />
          )}
          {step === 'done' && <DoneStep paid={paid} eventTitle={title} onPayNow={() => setStep('payment')} />}
        </div>

        {(step === 'tickets' || step === 'details') && (
          <aside className="lg:sticky lg:top-6 lg:self-start">
            <CartSummary cart={cart} />
            {step === 'tickets' && (
              <Button className="mt-3 w-full" disabled={itemCount === 0} onClick={() => setStep('details')}>
                Continue ({itemCount})
              </Button>
            )}
          </aside>
        )}
      </div>
    </div>
  );
}

// module-scoped attendee draft (kept out of render churn; reset on confirm)
const attendeesStore: { current: AttendeeInput[] } = { current: [] };

function Steps({ step }: { step: Step }) {
  const items: [Step, string][] = [
    ['tickets', 'Tickets'],
    ['details', 'Details'],
    ['review', 'Review'],
    ['payment', 'Payment'],
    ['done', 'Done'],
  ];
  const idx = items.findIndex(([s]) => s === step);
  return (
    <ol className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-sm">
      {items.map(([s, label], i) => (
        <li key={s} className={cn('flex items-center gap-1.5', i <= idx ? 'text-foreground' : 'text-muted-foreground')}>
          <span className={cn('flex size-5 items-center justify-center rounded-full text-[11px]', i < idx ? 'bg-primary text-primary-foreground' : i === idx ? 'bg-primary/15 text-primary' : 'bg-muted')}>
            {i < idx ? <Check className="size-3" /> : i + 1}
          </span>
          {label}
        </li>
      ))}
    </ol>
  );
}

function TicketsStep({
  slug,
  projectId,
  offerings,
  cart,
  onChange,
}: {
  slug: string;
  projectId: string;
  offerings: CheckoutOffering[];
  cart: Cart | null;
  onChange: () => Promise<void> | void;
}) {
  const [openSeats, setOpenSeats] = useState<string | null>(null);
  const gaQty = (id: string) => cart?.lines.find((l) => l.offeringId === id)?.qty ?? 0;
  const seatCount = (id: string) => cart?.lines.find((l) => l.offeringId === id)?.seatIds.length ?? 0;

  return (
    <div className="space-y-3">
      {offerings.map((o) => (
        <div key={o.id} className="rounded-xl border border-border bg-card p-4">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="space-y-1">
              <div className="flex items-center gap-2">
                <span className="font-medium">{o.productName}</span>
                {o.allocationMode === 'RESERVED' ? (
                  <Badge variant="info" appearance="light" size="sm"><Armchair className="size-3" /> Reserved</Badge>
                ) : (
                  <Badge variant="secondary" appearance="light" size="sm">General</Badge>
                )}
              </div>
              <p className="text-lg font-semibold">{formatMoney(o.price, o.currency)}</p>
            </div>
            {o.allocationMode === 'GA' ? (
              <Stepper
                value={gaQty(o.id)}
                onChange={async (q) => { await checkoutService.setGaQty(slug, projectId, o.id, q); await onChange(); }}
              />
            ) : (
              <Button variant={seatCount(o.id) ? 'primary' : 'outline'} onClick={() => setOpenSeats((c) => (c === o.id ? null : o.id))}>
                <Armchair className="size-4" />
                {seatCount(o.id) ? `${seatCount(o.id)} seat(s)` : 'Select seats'}
              </Button>
            )}
          </div>
          {openSeats === o.id && o.allocationMode === 'RESERVED' && (
            <SeatPicker slug={slug} projectId={projectId} offeringId={o.id} onChange={onChange} />
          )}
        </div>
      ))}
    </div>
  );
}

function Stepper({ value, onChange }: { value: number; onChange: (q: number) => void }) {
  return (
    <div className="flex items-center gap-2">
      <Button variant="outline" size="icon" disabled={value === 0} onClick={() => onChange(value - 1)} aria-label="Decrease">
        <Minus className="size-4" />
      </Button>
      <span className="w-8 text-center font-medium">{value}</span>
      <Button variant="outline" size="icon" onClick={() => onChange(value + 1)} aria-label="Increase">
        <Plus className="size-4" />
      </Button>
    </div>
  );
}

const SEAT_STYLE: Record<string, string> = {
  free: 'bg-success/15 text-success hover:bg-success/30',
  held: 'bg-muted-foreground/20 text-muted-foreground cursor-not-allowed',
  sold: 'bg-muted-foreground/20 text-muted-foreground cursor-not-allowed line-through',
  mine: 'bg-primary text-primary-foreground ring-2 ring-primary',
};

function SeatPicker({
  slug,
  projectId,
  offeringId,
  onChange,
}: {
  slug: string;
  projectId: string;
  offeringId: string;
  onChange: () => Promise<void> | void;
}) {
  const [rows, setRows] = useState<SeatRow[]>([]);
  const reload = useCallback(() => checkoutService.getSeatMap(slug, projectId, offeringId).then(setRows), [slug, projectId, offeringId]);
  useEffect(() => { reload(); }, [reload]);

  const click = async (seatId: string) => {
    await checkoutService.toggleSeat(slug, projectId, offeringId, seatId);
    await reload();
    await onChange();
  };

  return (
    <div className="mt-4 space-y-3 border-t border-border pt-4">
      <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
        <Legend className={SEAT_STYLE.free} label="Free" />
        <Legend className={SEAT_STYLE.mine} label="Selected" />
        <Legend className={SEAT_STYLE.sold} label="Taken" />
      </div>
      <div className="overflow-x-auto rounded-lg bg-muted/30 p-3">
        <div className="mx-auto mb-3 w-1/2 rounded bg-foreground/10 py-1 text-center text-[11px] uppercase tracking-wide text-muted-foreground">Stage</div>
        <div className="flex flex-col items-center gap-1.5">
          {rows.map((r) => (
            <div key={r.row} className="flex items-center gap-1.5">
              <span className="w-5 text-right text-xs text-muted-foreground">{r.row}</span>
              <div className="flex gap-1">
                {r.seats.map((s) => {
                  const key = s.mine ? 'mine' : s.status;
                  return (
                    <button
                      key={s.id}
                      type="button"
                      title={s.label}
                      disabled={!s.mine && s.status !== 'free'}
                      onClick={() => void click(s.id)}
                      className={cn('inline-flex h-7 min-w-7 items-center justify-center rounded px-1 text-[10px] font-medium transition-colors', SEAT_STYLE[key])}
                    >
                      {s.number}
                    </button>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function Legend({ className, label }: { className: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={cn('inline-block size-3 rounded', className)} />
      {label}
    </span>
  );
}

function CartSummary({ cart }: { cart: Cart | null }) {
  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <h2 className="mb-3 font-medium">Your order</h2>
      {!cart || cart.lines.length === 0 ? (
        <p className="text-muted-foreground text-sm">No tickets selected yet.</p>
      ) : (
        <>
          {cart.expiresAt && <Countdown expiresAt={cart.expiresAt} />}
          <ul className="space-y-2 text-sm">
            {cart.lines.map((l) => (
              <li key={l.offeringId} className="flex justify-between gap-2">
                <span>
                  {l.qty} × {l.productName}
                  {l.seatLabels.length > 0 && (
                    <span className="block text-xs text-muted-foreground">{l.seatLabels.join(', ')}</span>
                  )}
                </span>
                <span className="shrink-0">{formatMoney(l.unitPrice * l.qty, l.currency)}</span>
              </li>
            ))}
          </ul>
          <div className="mt-3 space-y-1 border-t border-border pt-3 text-sm">
            <Line label="Subtotal" value={formatMoney(cart.subtotal, cart.currency)} />
            <Line label="Tax" value={formatMoney(cart.tax, cart.currency)} />
            <div className="flex justify-between pt-1 font-semibold">
              <span>Total</span>
              <span>{formatMoney(cart.total, cart.currency)}</span>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function Line({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between text-muted-foreground">
      <span>{label}</span>
      <span>{value}</span>
    </div>
  );
}

function Countdown({ expiresAt }: { expiresAt: string }) {
  const [left, setLeft] = useState(() => Math.max(0, new Date(expiresAt).getTime() - Date.now()));
  useEffect(() => {
    const id = setInterval(() => setLeft(Math.max(0, new Date(expiresAt).getTime() - Date.now())), 1000);
    return () => clearInterval(id);
  }, [expiresAt]);
  const mm = Math.floor(left / 60000);
  const ss = Math.floor((left % 60000) / 1000);
  return (
    <div className="mb-3 flex items-center gap-1.5 rounded-md bg-warning/15 px-2.5 py-1.5 text-xs font-medium text-foreground">
      <Clock className="size-3.5 text-warning" />
      {left > 0 ? <span>Seats held — {mm}:{String(ss).padStart(2, '0')} left</span> : <span>Hold expired</span>}
    </div>
  );
}

function DetailsStep({
  cart,
  onBack,
  onNext,
  attendeesRef,
}: {
  cart: Cart;
  onBack: () => void;
  onNext: () => void;
  attendeesRef: { current: AttendeeInput[] };
}) {
  // one attendee per ticket (RESERVED → per seat; GA → per qty)
  const slots = useMemo<AttendeeInput[]>(() => {
    const out: AttendeeInput[] = [];
    for (const l of cart.lines) {
      if (l.allocationMode === 'RESERVED') {
        l.seatLabels.forEach((sl) => out.push({ offeringId: l.offeringId, seatLabel: sl, name: '', email: '', phone: '' }));
      } else {
        for (let i = 0; i < l.qty; i++) out.push({ offeringId: l.offeringId, seatLabel: null, name: '', email: '', phone: '' });
      }
    }
    return out;
  }, [cart]);

  const [attendees, setAttendees] = useState<AttendeeInput[]>(() =>
    attendeesRef.current.length === slots.length ? attendeesRef.current : slots,
  );
  const set = (i: number, k: keyof AttendeeInput, v: string) =>
    setAttendees((cur) => cur.map((a, idx) => (idx === i ? { ...a, [k]: v } : a)));

  const valid = attendees.every((a) => a.name.trim() && /\S+@\S+\.\S+/.test(a.email));

  const next = () => {
    attendeesRef.current = attendees;
    onNext();
  };

  return (
    <div className="space-y-4">
      <p className="text-muted-foreground text-sm">Tell us who’s attending. The first attendee is the purchaser.</p>
      {attendees.map((a, i) => (
        <div key={i} className={cn('rounded-xl border bg-card p-4', i === 0 ? 'border-primary/40 ring-1 ring-primary/20' : 'border-border')}>
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <Ticket className="size-4 text-muted-foreground" />
            <span className="text-sm font-medium">
              Ticket {i + 1}
              {a.seatLabel && <span className="text-muted-foreground"> · seat {a.seatLabel}</span>}
            </span>
            {i === 0 && (
              <Badge variant="primary" appearance="light" size="sm">Main contact</Badge>
            )}
          </div>
          <div className="grid gap-3 sm:grid-cols-3">
            <Field label="Full name *"><Input aria-label="Full name *" value={a.name} onChange={(e) => set(i, 'name', e.target.value)} /></Field>
            <Field label="Email *"><Input aria-label="Email *" type="email" value={a.email} onChange={(e) => set(i, 'email', e.target.value)} /></Field>
            <Field label="Phone"><Input aria-label="Phone" value={a.phone} onChange={(e) => set(i, 'phone', e.target.value)} /></Field>
          </div>
        </div>
      ))}
      <div className="flex justify-between">
        <Button variant="outline" onClick={onBack}>Back</Button>
        <Button disabled={!valid} onClick={next}>Continue</Button>
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <Label>{label}</Label>
      {children}
    </div>
  );
}

function ReviewStep({
  slug,
  projectId,
  cart,
  onBack,
  onReserved,
}: {
  slug: string;
  projectId: string;
  cart: Cart;
  onBack: () => void;
  onReserved: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const reserve = async () => {
    setBusy(true);
    try {
      const order = await checkoutService.confirm(slug, projectId, attendeesStore.current);
      orderStore.current = order;
      attendeesStore.current = [];
      onReserved();
    } catch (e) {
      // hold expired / capacity gone / network — tell the user, re-enable
      toast.error(e instanceof Error ? e.message : 'Could not confirm — your hold may have expired.');
      setBusy(false);
    }
  };
  return (
    <div className="space-y-4">
      <CartSummary cart={cart} />
      <div className="flex justify-between">
        <Button variant="outline" onClick={onBack} disabled={busy}>Back</Button>
        <Button onClick={() => void reserve()} disabled={busy}>{busy ? 'Reserving…' : 'Continue to payment'}</Button>
      </div>
    </div>
  );
}

function PaymentStep({ onPaid, onPayLater }: { onPaid: () => void; onPayLater: () => void }) {
  const order = orderStore.current;
  const [card, setCard] = useState('');
  const [exp, setExp] = useState('');
  const [cvc, setCvc] = useState('');
  const [busy, setBusy] = useState(false);
  const valid = card.replace(/\s/g, '').length >= 12 && /\d\d\/\d\d/.test(exp) && cvc.length >= 3;

  const pay = async () => {
    setBusy(true);
    // mock gateway — real provider lands in Cluster F
    await new Promise((r) => setTimeout(r, 500));
    onPaid();
  };

  return (
    <div className="mx-auto max-w-md space-y-4">
      <div className="rounded-xl border border-border bg-card p-5">
        <div className="mb-4 flex items-center justify-between">
          <span className="flex items-center gap-2 font-medium"><CreditCard className="size-4" /> Card payment</span>
          {order && <span className="text-lg font-semibold">{formatMoney(order.invoiceTotal, order.currency)}</span>}
        </div>
        <div className="space-y-3">
          <Field label="Card number">
            <Input aria-label="Card number" inputMode="numeric" placeholder="4242 4242 4242 4242" value={card} onChange={(e) => setCard(e.target.value)} />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Expiry (MM/YY)"><Input aria-label="Expiry (MM/YY)" placeholder="12/27" value={exp} onChange={(e) => setExp(e.target.value)} /></Field>
            <Field label="CVC"><Input aria-label="CVC" inputMode="numeric" placeholder="123" value={cvc} onChange={(e) => setCvc(e.target.value)} /></Field>
          </div>
        </div>
        <Button className="mt-4 w-full" disabled={!valid || busy} onClick={() => void pay()}>
          {busy ? 'Processing…' : order ? `Pay ${formatMoney(order.invoiceTotal, order.currency)}` : 'Pay'}
        </Button>
        <p className="mt-2 text-center text-xs text-muted-foreground">Demo payment — no real charge.</p>
      </div>
      <button type="button" onClick={onPayLater} className="mx-auto block text-sm text-muted-foreground underline-offset-2 hover:underline">
        I’ll pay later
      </button>
    </div>
  );
}

const orderStore: { current: import('@/types/registration').OrderResult | null } = { current: null };

function DoneStep({ paid, eventTitle, onPayNow }: { paid: boolean; eventTitle: string; onPayNow: () => void }) {
  const order = orderStore.current;
  const emails = order?.confirmationEmails.join(', ');
  // The Done screen just confirmed — render the REAL signed QR straight from the
  // live confirm result (AC-05-TKT-02). Only fall back to the mock portal when
  // there's genuinely no in-state result (e.g. a hard reload landing here).
  const liveTickets = order?.tickets ?? [];
  const [portal, setPortal] = useState<PortalOrder | null>(null);

  useEffect(() => {
    // TODO(BL): drop the mock getPortalOrder once a real portal-order endpoint
    // lands; it's only the no-in-state-result fallback.
    if (order && liveTickets.length === 0) {
      eventBillingService.getPortalOrder(order.orderRef, eventTitle, paid).then(setPortal);
    }
  }, [order, eventTitle, paid, liveTickets.length]);

  return (
    <div className="mx-auto max-w-lg py-8">
      <div className="text-center">
        <div className={cn('mx-auto mb-4 flex size-14 items-center justify-center rounded-full', paid ? 'bg-success/15 text-success' : 'bg-warning/15 text-warning')}>
          {paid ? <Check className="size-7" /> : <Clock className="size-7" />}
        </div>
        <h2 className="font-heading text-xl font-semibold">{paid ? 'You’re registered!' : 'Almost there — payment pending'}</h2>
        {order && (
          <p className="mt-1 text-sm text-muted-foreground">
            Order <span className="font-medium text-foreground">{order.orderRef}</span> · {order.ticketCount} ticket(s)
          </p>
        )}
      </div>

      {/* my tickets — real signed QR from the live confirm result */}
      {liveTickets.length > 0 && (
        <div className="mt-6 space-y-2">
          {liveTickets.map((t) => (
            <div key={t.ticketId} className="flex items-center justify-between gap-3 rounded-xl border border-border bg-card p-4">
              <div className="flex min-w-0 items-center gap-3">
                <Ticket className="size-5 shrink-0 text-primary" />
                <div className="flex min-w-0 flex-col">
                  <span className="truncate font-medium">{t.offeringName ?? 'Ticket'}</span>
                  {t.attendeeName && <span className="truncate text-xs text-muted-foreground">{t.attendeeName}</span>}
                </div>
              </div>
              {t.qrToken ? (
                <div className="shrink-0 rounded bg-white p-1">
                  <QRCodeSVG value={t.qrToken} size={56} aria-label="Ticket QR code" />
                </div>
              ) : (
                <div className="flex size-14 shrink-0 items-center justify-center rounded bg-foreground/5 text-[9px] text-muted-foreground">No QR</div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* fallback: mock portal view (no in-state confirm result) */}
      {liveTickets.length === 0 && portal && (
        <div className="mt-6 space-y-2">
          {portal.tickets.map((t) => (
            <div key={t.id} className="flex items-center justify-between rounded-xl border border-border bg-card p-4">
              <div className="flex items-center gap-3">
                <Ticket className="size-5 text-primary" />
                <div className="flex flex-col">
                  <span className="font-medium">{t.offeringName}{t.seatLabel ? ` · ${t.seatLabel}` : ''}</span>
                  <span className="text-xs text-muted-foreground">{t.attendeeName}</span>
                </div>
              </div>
              <div className="flex size-12 items-center justify-center rounded bg-foreground/5 text-[9px] text-muted-foreground">QR</div>
            </div>
          ))}
        </div>
      )}

      {/* invoice summary (portal) */}
      {order && (
        <div className="mt-4 rounded-xl border border-border bg-card p-4">
          <div className="flex items-center justify-between">
            <span className="text-sm text-muted-foreground">Invoice total</span>
            <span className="font-semibold">{formatMoney(order.invoiceTotal, order.currency)}</span>
          </div>
          <div className="mt-2 flex items-center justify-between">
            <span className="text-sm text-muted-foreground">Payment</span>
            {paid ? (
              <Badge variant="success" appearance="light" size="sm">Paid</Badge>
            ) : (
              <Badge variant="warning" appearance="light" size="sm">Pending</Badge>
            )}
          </div>
          {paid ? (
            emails && <p className="mt-3 text-xs text-muted-foreground">A confirmation email + your tickets were sent to {emails}.</p>
          ) : (
            <p className="mt-3 text-xs text-muted-foreground">We’ve emailed {emails} a link to complete payment. Your seats are held until the timer expires.</p>
          )}
        </div>
      )}

      {!paid && <Button className="mt-5 w-full" onClick={onPayNow}>Complete payment</Button>}
    </div>
  );
}
