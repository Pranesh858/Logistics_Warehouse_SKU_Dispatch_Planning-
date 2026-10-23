'use client';

import { useMemo, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { errorMessage } from '@/lib/api';
import { useAddTruck, useEditTruck, useRemoveTruck, useTrucks } from '../hooks';
import type { Truck } from '../types';

export function TruckSetup({ warehouses, readOnly = false }: { warehouses: string[]; readOnly?: boolean }) {
  const trucks = useTrucks();
  const add = useAddTruck();
  const edit = useEditTruck();
  const remove = useRemoveTruck();
  const [name, setName] = useState('');
  const [wh, setWh] = useState('');
  const [cap, setCap] = useState('120');
  const [error, setError] = useState<string | null>(null);

  const whList = useMemo(() => Array.from(new Set([...warehouses, ...(trucks.data ?? []).map((t) => t.warehouse_id)])).sort(), [warehouses, trucks.data]);
  const fail = (e: unknown) => setError(errorMessage(e));

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    add.mutate({ name: name.trim(), warehouse_id: wh || whList[0], capacity_units: Number(cap) }, {
      onSuccess: () => setName(''),
      onError: fail,
    });
  };

  return (
    <div className="space-y-5">
      <p className="text-caption text-ink-muted max-w-2xl">
        A truck loads from one warehouse and holds up to its capacity in units. The plan is loaded onto these trucks in priority order.
        Changing a truck re-loads the plan straight away.
      </p>

      {!readOnly && <form onSubmit={submit} className="flex flex-wrap items-end gap-3 rounded-md border border-surface-line bg-surface-muted p-4">
        <label className="text-label text-ink-muted">Truck name
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. WH01-Large" className="mt-1 w-44" required />
        </label>
        <label className="text-label text-ink-muted">Warehouse
          <select value={wh || whList[0] || ''} onChange={(e) => setWh(e.target.value)} className="mt-1 h-9 rounded-md border border-input bg-surface px-2 text-body-sm">
            {whList.map((w) => <option key={w}>{w}</option>)}
          </select>
        </label>
        <label className="text-label text-ink-muted">Capacity (units)
          <Input type="number" min={1} step="any" value={cap} onChange={(e) => setCap(e.target.value)} className="mt-1 w-32" required />
        </label>
        <Button type="submit" disabled={add.isPending || !name.trim() || Number(cap) <= 0}>Add truck</Button>
      </form>}
      {error && <p role="alert" className="rounded-md border border-danger-border bg-danger-soft px-3 py-2 text-body-sm text-danger-text">{error}</p>}

      {trucks.isLoading ? <p className="text-ink-muted">Loading trucks…</p> : (
        <div className="overflow-x-auto">
          <table className="w-full text-body-sm">
            <thead><tr className="border-b border-surface-line text-left text-label text-ink-muted">
              <th className="py-2 pr-3">Truck</th><th className="pr-3">Warehouse</th><th className="pr-3 text-right">Capacity (units)</th><th className="w-24" />
            </tr></thead>
            <tbody>
              {(trucks.data ?? []).map((t) => (
                <TruckRow key={t.id} truck={t} readOnly={readOnly} busy={edit.isPending || remove.isPending}
                  onSave={(body) => { setError(null); edit.mutate({ id: t.id, body }, { onError: fail }); }}
                  onRemove={() => { setError(null); remove.mutate(t.id, { onError: fail }); }} />
              ))}
              {!trucks.data?.length && <tr><td colSpan={4} className="py-8 text-center text-ink-muted">No trucks yet. Add one above.</td></tr>}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function TruckRow({ truck, busy, readOnly, onSave, onRemove }: {
  truck: Truck; busy: boolean; readOnly: boolean; onSave: (body: { name?: string; capacity_units?: number }) => void; onRemove: () => void;
}) {
  const [name, setName] = useState(truck.name);
  const [cap, setCap] = useState(String(truck.capacity_units));
  const dirty = name.trim() !== truck.name || Number(cap) !== truck.capacity_units;
  return (
    <tr className="border-b border-surface-line">
      <td className="py-1.5 pr-3"><Input aria-label={`Name of ${truck.name}`} readOnly={readOnly} value={name} onChange={(e) => setName(e.target.value)} className="h-8 w-44" /></td>
      <td className="pr-3 text-ink-body">{truck.warehouse_id}</td>
      <td className="pr-3 text-right"><Input aria-label={`Capacity of ${truck.name}`} readOnly={readOnly} type="number" min={1} step="any" value={cap}
        onChange={(e) => setCap(e.target.value)} className="ml-auto h-8 w-28 text-right tabular" /></td>
      <td className="whitespace-nowrap text-right">
        {readOnly ? null : dirty
          ? <Button size="sm" disabled={busy || !name.trim() || Number(cap) <= 0}
              onClick={() => onSave({ name: name.trim(), capacity_units: Number(cap) })}>Save</Button>
          : <Button size="sm" variant="ghost" disabled={busy} onClick={onRemove} aria-label={`Remove ${truck.name}`}>Remove</Button>}
      </td>
    </tr>
  );
}

