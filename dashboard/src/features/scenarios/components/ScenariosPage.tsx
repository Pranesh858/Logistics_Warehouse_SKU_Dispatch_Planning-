'use client';

import { useMemo, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Notice, Section } from '@/components/ui/section';
import { Table, TableFrame, TD, TH, THead, TR } from '@/components/ui/table';
import { PageBody, PageHeader } from '@/components/layout/PageHeader';
import { WarehouseSwitch } from '@/features/auth/components/WarehouseSwitch';
import { useCan, useScope } from '@/features/auth/store';
import { useWarehouseList } from '@/features/dispatch/hooks';
import { useSkus } from '@/features/forecast/hooks';
import { errorMessage } from '@/lib/api';
import { useRunScenario } from '../hooks';
import type { ScenarioIn, ScenarioResult, ScenarioSummary } from '../types';

const SELECT =
  'flex h-comp-md w-full rounded-md border border-input bg-surface px-2.5 text-body-sm text-ink-heading hover:border-ink-subtle focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring';

type DemandRow = { key: number; target: 'category' | 'sku'; category: string; sku: string; pct: string };
type StockRow = { key: number; warehouse: string; pct: string };
type BlockRow = { key: number; sku: string; warehouse: string };

/** Which figures are compared. `better` says which way is good, so a change can be coloured. */
const ROWS: { key: keyof ScenarioSummary; label: string; unit?: string; better: 'up' | 'down' | null }[] = [
  { key: 'fill_rate_pct', label: 'Fill rate', unit: '%', better: 'up' },
  { key: 'order_fill_rate_pct', label: 'Orders fully planned', unit: '%', better: 'up' },
  { key: 'units_ordered', label: 'Units ordered', better: null },
  { key: 'units_planned', label: 'Units planned', better: 'up' },
  { key: 'partial', label: 'Partly filled orders', better: 'down' },
  { key: 'held', label: 'Held whole', better: 'down' },
  { key: 'backordered', label: 'Out of stock', better: 'down' },
  { key: 'blocked', label: 'Blocked', better: 'down' },
  { key: 'at_risk', label: 'Orders at risk', better: 'down' },
];

const num = (v: number | null | undefined, unit = '') =>
  v === null || v === undefined ? '—' : `${v.toLocaleString(undefined, { maximumFractionDigits: 1 })}${unit}`;

/** Try a change on a copy of the plan before it happens. Nothing here reaches the plan, the stock or the WMS. */
export function ScenariosPage() {
  const can = useCan();
  const scope = useScope();
  const skus = useSkus();
  const warehouses = useWarehouseList();
  const run = useRunScenario();

  const [nextKey, setNextKey] = useState(1);
  const [demand, setDemand] = useState<DemandRow[]>([]);
  const [stock, setStock] = useState<StockRow[]>([]);
  const [block, setBlock] = useState<BlockRow[]>([]);
  const key = () => { setNextKey((k) => k + 1); return nextKey; };

  const categories = useMemo(() => Array.from(new Set((skus.data ?? []).map((s) => s.category))).sort(), [skus.data]);
  const whList = scope ? [scope] : warehouses.data ?? [];

  const body = (): ScenarioIn => ({
    demand: demand.map((d) => ({
      ...(d.target === 'sku' ? { product_id: Number(d.sku) } : { category: d.category || categories[0] }),
      multiplier: 1 + Number(d.pct) / 100,
    })),
    stock: stock.map((s) => ({ warehouse_id: s.warehouse || whList[0], change_pct: Number(s.pct) })),
    block: block.map((b) => ({ product_id: Number(b.sku), ...(b.warehouse ? { warehouse_id: b.warehouse } : {}) })),
    warehouse_id: scope ?? undefined,
  });

  const count = demand.length + stock.length + block.length;
  const complete = count > 0
    && demand.every((d) => d.pct !== '' && Number(d.pct) > -100 && (d.target === 'sku' ? Number(d.sku) > 0 : !!(d.category || categories[0])))
    && stock.every((s) => s.pct !== '' && !!(s.warehouse || whList[0]))
    && block.every((b) => Number(b.sku) > 0);

  return (
    <>
      <PageHeader title="Scenarios"
        lead="Try a change on a copy of the plan and compare it with the current one. Nothing is saved or sent."
        actions={<WarehouseSwitch />} />
      <PageBody className="space-y-5">
        {!can.edit && <Notice tone="info">Scenarios are for planners and admins.</Notice>}
        {can.edit && (
          <>
            <div className="grid gap-5 lg:grid-cols-3">
              <Section title="Demand" lead="Open orders not yet sent, up or down. The plan works from orders, not the forecast."
                actions={<Button size="sm" variant="outline" onClick={() => setDemand((r) => [...r, { key: key(), target: 'category', category: categories[0] ?? '', sku: '', pct: '20' }])}>Add</Button>}>
                <div className="space-y-2">
                  {demand.map((d, i) => (
                    <div key={d.key} className="grid grid-cols-[1fr_1fr_5rem_auto] items-end gap-2 rounded-md border border-surface-line bg-surface p-2.5">
                      <div className="space-y-1">
                        <Label htmlFor={`demand-target-${d.key}`}>Applies to</Label>
                        <select id={`demand-target-${d.key}`} className={SELECT} value={d.target}
                          onChange={(e) => setDemand((r) => r.map((x, j) => (j === i ? { ...x, target: e.target.value as DemandRow['target'] } : x)))}>
                          <option value="category">Category</option>
                          <option value="sku">SKU</option>
                        </select>
                      </div>
                      {d.target === 'category' ? (
                        <div className="space-y-1">
                          <Label htmlFor={`demand-cat-${d.key}`}>Category</Label>
                          <select id={`demand-cat-${d.key}`} className={SELECT} value={d.category || categories[0] || ''}
                            onChange={(e) => setDemand((r) => r.map((x, j) => (j === i ? { ...x, category: e.target.value } : x)))}>
                            {categories.map((c) => <option key={c}>{c}</option>)}
                          </select>
                        </div>
                      ) : (
                        <div className="space-y-1">
                          <Label htmlFor={`demand-sku-${d.key}`}>SKU</Label>
                          <Input id={`demand-sku-${d.key}`} type="number" min={1} value={d.sku}
                            onChange={(e) => setDemand((r) => r.map((x, j) => (j === i ? { ...x, sku: e.target.value } : x)))} />
                        </div>
                      )}
                      <div className="space-y-1">
                        <Label htmlFor={`demand-pct-${d.key}`}>Change %</Label>
                        <Input id={`demand-pct-${d.key}`} type="number" min={-99} max={900} value={d.pct}
                          onChange={(e) => setDemand((r) => r.map((x, j) => (j === i ? { ...x, pct: e.target.value } : x)))} />
                      </div>
                      <Button size="sm" variant="ghost" aria-label="Remove demand change" onClick={() => setDemand((r) => r.filter((_, j) => j !== i))}>Remove</Button>
                    </div>
                  ))}
                  {demand.length === 0 && <p className="text-caption text-ink-subtle">No demand change.</p>}
                </div>
              </Section>

              <Section title="Stock" lead="Everything on the shelf at a warehouse, up or down."
                actions={<Button size="sm" variant="outline" onClick={() => setStock((r) => [...r, { key: key(), warehouse: whList[0] ?? '', pct: '-10' }])}>Add</Button>}>
                <div className="space-y-2">
                  {stock.map((s, i) => (
                    <div key={s.key} className="grid grid-cols-[1fr_5rem_auto] items-end gap-2 rounded-md border border-surface-line bg-surface p-2.5">
                      <div className="space-y-1">
                        <Label htmlFor={`stock-wh-${s.key}`}>Warehouse</Label>
                        <select id={`stock-wh-${s.key}`} className={SELECT} value={s.warehouse || whList[0] || ''}
                          onChange={(e) => setStock((r) => r.map((x, j) => (j === i ? { ...x, warehouse: e.target.value } : x)))}>
                          {whList.map((w) => <option key={w}>{w}</option>)}
                        </select>
                      </div>
                      <div className="space-y-1">
                        <Label htmlFor={`stock-pct-${s.key}`}>Change %</Label>
                        <Input id={`stock-pct-${s.key}`} type="number" min={-100} max={500} value={s.pct}
                          onChange={(e) => setStock((r) => r.map((x, j) => (j === i ? { ...x, pct: e.target.value } : x)))} />
                      </div>
                      <Button size="sm" variant="ghost" aria-label="Remove stock change" onClick={() => setStock((r) => r.filter((_, j) => j !== i))}>Remove</Button>
                    </div>
                  ))}
                  {stock.length === 0 && <p className="text-caption text-ink-subtle">No stock change.</p>}
                </div>
              </Section>

              <Section title="Block SKUs" lead="As if these could not be dispatched."
                actions={<Button size="sm" variant="outline" onClick={() => setBlock((r) => [...r, { key: key(), sku: '', warehouse: scope ?? '' }])}>Add</Button>}>
                <div className="space-y-2">
                  {block.map((b, i) => (
                    <div key={b.key} className="grid grid-cols-[1fr_1fr_auto] items-end gap-2 rounded-md border border-surface-line bg-surface p-2.5">
                      <div className="space-y-1">
                        <Label htmlFor={`block-sku-${b.key}`}>SKU</Label>
                        <Input id={`block-sku-${b.key}`} type="number" min={1} value={b.sku}
                          onChange={(e) => setBlock((r) => r.map((x, j) => (j === i ? { ...x, sku: e.target.value } : x)))} />
                      </div>
                      <div className="space-y-1">
                        <Label htmlFor={`block-wh-${b.key}`}>Warehouse</Label>
                        <select id={`block-wh-${b.key}`} className={SELECT} value={b.warehouse}
                          onChange={(e) => setBlock((r) => r.map((x, j) => (j === i ? { ...x, warehouse: e.target.value } : x)))}>
                          {!scope && <option value="">All</option>}
                          {whList.map((w) => <option key={w}>{w}</option>)}
                        </select>
                      </div>
                      <Button size="sm" variant="ghost" aria-label="Remove blocked SKU" onClick={() => setBlock((r) => r.filter((_, j) => j !== i))}>Remove</Button>
                    </div>
                  ))}
                  {block.length === 0 && <p className="text-caption text-ink-subtle">No SKU blocked.</p>}
                </div>
              </Section>
            </div>

            <div className="flex justify-end">
              <Button disabled={!complete || run.isPending} onClick={() => run.mutate(body())}>
                {run.isPending ? 'Running…' : 'Run scenario'}
              </Button>
            </div>

            {run.isError && <Notice>{errorMessage(run.error)}</Notice>}
            {run.data && <Comparison result={run.data} />}
          </>
        )}
      </PageBody>
    </>
  );
}

function Comparison({ result }: { result: ScenarioResult }) {
  return (
    <Section title="Before and after"
      lead={`Plan v${result.plan_version ?? '—'}${result.warehouse_id ? ` at ${result.warehouse_id}` : ', all warehouses'}, as recommended, against the same plan with your changes. Planner overrides are left out of both.`}>
      <div className="space-y-2">
        {result.open_orders === 0 && (
          <Notice tone="info">
            {result.before.orders > 0
              ? `All ${result.before.orders.toLocaleString()} orders here have already been sent, so changes have nothing to act on. Try it when there are open orders.`
              : 'There are no orders here, so changes have nothing to act on.'}
          </Notice>
        )}
        {result.plan_changes.length > 0 && (
          <Notice tone="warn">
            The current plan is out of date ({result.plan_changes.join(', ')}), so part of the change below comes from that. Generate a plan first for a clean comparison.
          </Notice>
        )}
        <TableFrame>
          <Table>
            <THead>
              <tr><TH>Figure</TH><TH align="right">Current plan</TH><TH align="right">With your changes</TH><TH align="right">Change</TH></tr>
            </THead>
            <tbody>
              {ROWS.map((r) => {
                const change = result.difference[r.key];
                const good = change === null || change === undefined || change === 0 || r.better === null
                  ? null : (change > 0) === (r.better === 'up');
                return (
                  <TR key={r.key}>
                    <TD strong>{r.label}</TD>
                    <TD align="right">{num(result.before[r.key], r.unit)}</TD>
                    <TD align="right">{num(result.after[r.key], r.unit)}</TD>
                    <TD align="right" className={good === null ? 'text-ink-muted' : good ? 'text-success-text' : 'text-danger-text'}>
                      {change ? `${change > 0 ? '+' : ''}${num(change, r.unit)}` : 'no change'}
                    </TD>
                  </TR>
                );
              })}
            </tbody>
          </Table>
        </TableFrame>
      </div>
    </Section>
  );
}
