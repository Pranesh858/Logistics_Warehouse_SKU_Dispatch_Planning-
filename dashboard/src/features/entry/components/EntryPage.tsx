'use client';

import { useEffect, useMemo, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Notice, Section } from '@/components/ui/section';
import { PageBody, PageHeader } from '@/components/layout/PageHeader';
import { errorMessage } from '@/lib/api';
import { useCan, useScope } from '@/features/auth/store';
import { useSkus } from '@/features/forecast/hooks';
import type { SkuRow } from '@/features/forecast/types';
import { useAddOrder, useSetStock } from '../hooks';
import type { NewOrder } from '../types';

const SELECT =
  'flex h-comp-md w-full rounded-md border border-input bg-surface px-2.5 text-body-sm text-ink-heading hover:border-ink-subtle focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring';

const pad = (n: number) => String(n).padStart(2, '0');

/** "2026-10-28T18:30:00": local time with no zone, which is how the backend stores every order time. */
export const localStamp = (d: Date) =>
  `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;

/** Order numbers typed in here are recognisable on every other screen, and cannot collide with the ERP's. */
export function newOrderId(now = new Date()) {
  const stamp = `${String(now.getFullYear()).slice(2)}${pad(now.getMonth() + 1)}${pad(now.getDate())}${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
  return `MAN-${stamp}-${Math.floor(Math.random() * 36 ** 2).toString(36).toUpperCase().padStart(2, '0')}`;
}

/** Tomorrow at 18:00, the usual cut-off for a next-day delivery. */
export function defaultDue(now = new Date()) {
  const d = new Date(now);
  d.setDate(d.getDate() + 1);
  d.setHours(18, 0, 0, 0);
  return localStamp(d).slice(0, 16);
}

/**
 * Where people tell the system what just happened.
 *
 * Without a WMS or ERP connected, this is the way new orders and stock counts get in. Both are saved to the
 * database, and the dispatch plan is rebuilt before the screen says "done", so the person sees the effect.
 */
export function EntryPage() {
  const can = useCan();
  const skus = useSkus();

  return (
    <>
      <PageHeader
        title="Orders and stock"
        lead="Type in a new order or a stock count. The plan is rebuilt as soon as you save."
      />
      <PageBody className="space-y-5">
        {!can.edit && <Notice tone="info">You have view-only access, so nothing here can be changed.</Notice>}
        {skus.isError && <Notice>{errorMessage(skus.error)}</Notice>}
        {skus.isLoading && <p className="py-10 text-center text-body-sm text-ink-muted">Loading…</p>}
        {skus.data && can.edit && (
          <div className="grid gap-5 lg:grid-cols-2">
            <OrderForm skus={skus.data} />
            <StockForm skus={skus.data} />
          </div>
        )}
      </PageBody>
    </>
  );
}

/** Warehouse, then SKU. A planner's warehouse is fixed; everyone else picks. */
function SkuPicker({ skus, idPrefix, wh, setWh, pid, setPid }: {
  skus: SkuRow[]; idPrefix: string; wh: string; setWh: (v: string) => void; pid: number | null; setPid: (v: number) => void;
}) {
  const warehouses = useMemo(() => Array.from(new Set(skus.map((s) => s.warehouse_id))).sort(), [skus]);
  const here = useMemo(() => skus.filter((s) => s.warehouse_id === wh).sort((a, b) => a.product_id - b.product_id), [skus, wh]);

  return (
    <>
      <div className="space-y-1">
        <Label htmlFor={`${idPrefix}-wh`}>Warehouse</Label>
        <select id={`${idPrefix}-wh`} value={wh} onChange={(e) => setWh(e.target.value)} className={SELECT}
          disabled={warehouses.length === 1}>
          {warehouses.map((w) => <option key={w} value={w}>{w}</option>)}
        </select>
      </div>
      <div className="space-y-1">
        <Label htmlFor={`${idPrefix}-sku`}>SKU</Label>
        <select id={`${idPrefix}-sku`} value={pid ?? ''} onChange={(e) => setPid(Number(e.target.value))} className={SELECT}>
          {here.map((s) => (
            <option key={s.product_id} value={s.product_id}>
              {`SKU ${s.product_id} · ${s.category} · ${Math.round(s.stock_on_hand)} on hand`}
            </option>
          ))}
        </select>
      </div>
    </>
  );
}

/** The warehouse and SKU being worked on, kept valid when the list changes under it (a refetch, a new scope). */
function usePick(skus: SkuRow[]) {
  const scope = useScope();
  const first = (w: string) => skus.filter((s) => s.warehouse_id === w).sort((a, b) => a.product_id - b.product_id)[0]?.product_id ?? null;
  const warehouses = useMemo(() => Array.from(new Set(skus.map((s) => s.warehouse_id))).sort(), [skus]);
  const [wh, setWhState] = useState(scope && warehouses.includes(scope) ? scope : warehouses[0] ?? '');
  const [pid, setPid] = useState<number | null>(first(wh));

  const setWh = (w: string) => { setWhState(w); setPid(first(w)); };
  const sku = skus.find((s) => s.warehouse_id === wh && s.product_id === pid) ?? null;
  return { wh, setWh, pid, setPid, sku };
}

function OrderForm({ skus }: { skus: SkuRow[] }) {
  const { wh, setWh, pid, setPid, sku } = usePick(skus);
  const [qty, setQty] = useState('');
  const [customer, setCustomer] = useState('');
  const [tier, setTier] = useState<NewOrder['customer_tier']>('Standard');
  const [due, setDue] = useState(defaultDue());
  const add = useAddOrder();
  const [added, setAdded] = useState<{ id: string; allocated: number; ordered: number } | null>(null);

  const units = Number(qty);
  const valid = sku !== null && units > 0 && customer.trim() !== '' && due !== '';

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!valid || !sku) return;
    const order: NewOrder = {
      order_id: newOrderId(), order_timestamp: localStamp(new Date()), customer_id: customer.trim(),
      customer_tier: tier, product_id: sku.product_id, warehouse_id: sku.warehouse_id, qty_ordered: units,
      due_date: `${due}:00`,
    };
    setAdded(null);
    add.mutate(order, {
      onSuccess: (plan) => {
        const mine = plan.lines.find((l) => l.order_id === order.order_id);
        setAdded({ id: order.order_id, ordered: units, allocated: mine?.qty_allocated ?? 0 });
        setQty('');
      },
    });
  };

  return (
    <Section title="Add an order" lead="A customer order that came in by phone, email or counter.">
      <form onSubmit={submit} className="space-y-3 rounded-md border border-surface-line bg-surface p-4">
        <SkuPicker skus={skus} idPrefix="order" wh={wh} setWh={setWh} pid={pid} setPid={setPid} />
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1">
            <Label htmlFor="order-qty">Units ordered</Label>
            <Input id="order-qty" type="number" min={1} step={1} inputMode="numeric" value={qty}
              onChange={(e) => setQty(e.target.value)} />
          </div>
          <div className="space-y-1">
            <Label htmlFor="order-tier">Customer tier</Label>
            <select id="order-tier" value={tier} onChange={(e) => setTier(e.target.value as NewOrder['customer_tier'])} className={SELECT}>
              <option>Premium</option>
              <option>Standard</option>
              <option>Basic</option>
            </select>
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1">
            <Label htmlFor="order-customer">Customer ID</Label>
            <Input id="order-customer" value={customer} onChange={(e) => setCustomer(e.target.value)} maxLength={40} />
          </div>
          <div className="space-y-1">
            <Label htmlFor="order-due">Needed by</Label>
            <Input id="order-due" type="datetime-local" value={due} onChange={(e) => setDue(e.target.value)} />
          </div>
        </div>
        {add.isError && <Notice>{errorMessage(add.error)}</Notice>}
        {added && (
          <Notice tone={added.allocated >= added.ordered ? 'good' : 'warn'}>
            {`Order ${added.id} saved. ${
              added.allocated >= added.ordered
                ? 'The plan can fill all of it.'
                : `The plan can fill ${added.allocated} of ${added.ordered} units with the stock on hand.`
            }`}
          </Notice>
        )}
        <div className="flex justify-end">
          <Button type="submit" disabled={!valid || add.isPending}>{add.isPending ? 'Saving…' : 'Save order'}</Button>
        </div>
      </form>
    </Section>
  );
}

function StockForm({ skus }: { skus: SkuRow[] }) {
  const { wh, setWh, pid, setPid, sku } = usePick(skus);
  const [units, setUnits] = useState('');
  const [reason, setReason] = useState('');
  const set = useSetStock();
  const [saved, setSaved] = useState<{ before: number; after: number; changed: boolean } | null>(null);

  // Start from what the system believes is on the shelf, so the change is a correction rather than a retype.
  const current = sku?.stock_on_hand;
  useEffect(() => {
    setUnits(current === undefined ? '' : String(Math.round(current)));
    setSaved(null);
  }, [wh, pid]); // eslint-disable-line react-hooks/exhaustive-deps

  const n = Number(units);
  const valid = sku !== null && units !== '' && Number.isFinite(n) && n >= 0;

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!valid || !sku) return;
    const before = sku.stock_on_hand;
    setSaved(null);
    set.mutate(
      { item: { product_id: sku.product_id, warehouse_id: sku.warehouse_id, stock_on_hand: n }, reason: reason.trim() },
      { onSuccess: (r) => { setSaved({ before, after: n, changed: r.changed > 0 }); setReason(''); } },
    );
  };

  return (
    <Section title="Set stock" lead="A stock count, goods received, or a write-off. The number you enter replaces the current one.">
      <form onSubmit={submit} className="space-y-3 rounded-md border border-surface-line bg-surface p-4">
        <SkuPicker skus={skus} idPrefix="stock" wh={wh} setWh={setWh} pid={pid} setPid={setPid} />
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1">
            <Label htmlFor="stock-units">Units on the shelf now</Label>
            <Input id="stock-units" type="number" min={0} step={1} inputMode="numeric" value={units}
              onChange={(e) => setUnits(e.target.value)} />
          </div>
          <div className="space-y-1">
            <Label htmlFor="stock-reason">Reason (optional)</Label>
            <Input id="stock-reason" value={reason} onChange={(e) => setReason(e.target.value)} maxLength={200}
              placeholder="e.g. delivery received" />
          </div>
        </div>
        {set.isError && <Notice>{errorMessage(set.error)}</Notice>}
        {saved && (
          <Notice tone="good">
            {saved.changed
              ? `Stock changed from ${Math.round(saved.before)} to ${saved.after}. The plan has been rebuilt.`
              : 'That is already the number on record, so nothing changed.'}
          </Notice>
        )}
        <div className="flex justify-end">
          <Button type="submit" disabled={!valid || set.isPending}>{set.isPending ? 'Saving…' : 'Save stock'}</Button>
        </div>
      </form>
    </Section>
  );
}
