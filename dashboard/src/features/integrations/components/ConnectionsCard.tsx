'use client';

import { useState } from 'react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { errorMessage } from '@/lib/api';
import { useSaveSystem, useTestConnection } from '../hooks';
import type { SystemSettings } from '../types';

const TITLE: Record<string, { name: string; what: string; feeds: { key: string; label: string }[] }> = {
  wms: {
    name: 'Warehouse system (WMS)', what: 'Stock levels come in from here, and approved dispatch orders go out to it.',
    feeds: [{ key: 'inventory', label: 'Stock levels' }],
  },
  erp: {
    name: 'ERP', what: 'Customer orders and sales history come in from here, and purchase orders go out to it.',
    feeds: [{ key: 'orders', label: 'Customer orders' }, { key: 'sales', label: 'Sales history' }],
  },
};

/** Lines like "inventory.product_id = sku" become {inventory: {product_id: "sku"}}. */
function parseMap(text: string): Record<string, Record<string, string>> {
  const out: Record<string, Record<string, string>> = {};
  text.split('\n').forEach((line) => {
    const [left, right] = line.split('=');
    if (!left || !right) return;
    const [feed, ours] = left.trim().split('.');
    if (!feed || !ours) return;
    out[feed] = { ...(out[feed] ?? {}), [ours]: right.trim() };
  });
  return out;
}

function printMap(map: Record<string, Record<string, string>>): string {
  return Object.entries(map ?? {})
    .flatMap(([feed, fields]) => Object.entries(fields ?? {}).map(([ours, theirs]) => `${feed}.${ours} = ${theirs}`))
    .join('\n');
}

export function ConnectionsCard({ systems }: { systems: Record<'wms' | 'erp', SystemSettings> }) {
  return (
    <section className="rounded-md border border-surface-line bg-surface">
      <header className="border-b border-surface-line px-4 py-2.5">
        <h2 className="text-h3 text-ink-heading">Connect your own systems</h2>
        <p className="text-caption text-ink-muted">
          Until a system is switched on here, that side runs on a built-in simulator. No code change is needed to move to a real one.
        </p>
      </header>
      <div className="grid gap-4 p-4 lg:grid-cols-2">
        {(['wms', 'erp'] as const).map((key) => <SystemForm key={key} system={key} saved={systems[key]} />)}
      </div>
    </section>
  );
}

function SystemForm({ system, saved }: { system: 'wms' | 'erp'; saved: SystemSettings }) {
  const meta = TITLE[system];
  const save = useSaveSystem();
  const probe = useTestConnection();
  const [url, setUrl] = useState(saved.base_url);
  const [key, setKey] = useState('');
  const [on, setOn] = useState(saved.enabled);
  const [map, setMap] = useState(printMap(saved.field_map));
  const [mins, setMins] = useState<Record<string, number>>(saved.sync_minutes ?? {});
  const [feed, setFeed] = useState(meta.feeds[0].key);
  const [saved2, setSaved2] = useState(false);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    setSaved2(false);
    save.mutate(
      { system, body: { base_url: url.trim(), api_key: key ? key : null, enabled: on, field_map: parseMap(map), sync_minutes: mins } },
      { onSuccess: () => { setKey(''); setSaved2(true); } },
    );
  };

  const result = probe.data;

  return (
    <form onSubmit={submit} className="space-y-3 rounded-md border border-surface-line bg-surface-muted p-3">
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-h4 text-ink-heading">{meta.name}</p>
          <p className="text-caption text-ink-muted">{meta.what}</p>
        </div>
        <Badge variant={saved.enabled ? 'success' : 'secondary'}>{saved.enabled ? 'Connected' : 'Simulator'}</Badge>
      </div>

      <div className="space-y-1.5">
        <Label htmlFor={`${system}-url`}>Address</Label>
        <Input id={`${system}-url`} className="h-comp-sm" value={url} onChange={(e) => setUrl(e.target.value)} placeholder={system === "wms" ? "https://wms.yourcompany.com/api" : "https://erp.yourcompany.com/api"} />
      </div>

      <div className="space-y-1.5">
        <Label htmlFor={`${system}-key`}>Access key</Label>
        <Input id={`${system}-key`} type="password" className="h-comp-sm" value={key} onChange={(e) => setKey(e.target.value)}
          placeholder={saved.has_key ? 'A key is saved. Type to replace it.' : 'Sent as a bearer token'} />
      </div>

      <div className="flex flex-wrap gap-4">
        {meta.feeds.map((f) => (
          <div key={f.key} className="space-y-1.5">
            <Label htmlFor={`${system}-${f.key}-min`}>{f.label}, check every</Label>
            <div className="flex items-center gap-2">
              <Input id={`${system}-${f.key}-min`} type="number" min={0} max={10080} className="h-comp-sm w-20"
                value={mins[f.key] ?? 0} onChange={(e) => setMins({ ...mins, [f.key]: Number(e.target.value) || 0 })} />
              <span className="text-caption text-ink-muted">min (0 = manual)</span>
            </div>
          </div>
        ))}
      </div>

      <details className="text-body-sm">
        <summary className="cursor-pointer text-ink-muted">Field names, if this system calls things something else</summary>
        <textarea value={map} onChange={(e) => setMap(e.target.value)} rows={3} spellCheck={false}
          className="mt-2 w-full rounded-md border border-input bg-surface p-2 font-mono text-caption text-ink-body"
          placeholder={`${meta.feeds[0].key}.product_id = sku`} />
        <p className="mt-1 text-caption text-ink-muted">One per line: what we call it on the left, what they call it on the right.</p>
      </details>

      <label className="flex items-center gap-2 text-caption text-ink-body">
        <input type="checkbox" checked={on} onChange={(e) => setOn(e.target.checked)} className="h-3.5 w-3.5 accent-[#1F4B8E]" />
        Use this system instead of the simulator
      </label>

      <div className="flex flex-wrap items-center gap-2">
        <Button type="submit" size="sm" disabled={save.isPending}>{save.isPending ? 'Saving…' : 'Save'}</Button>
        <select aria-label="Feed to test" value={feed} onChange={(e) => setFeed(e.target.value)}
          className="h-comp-sm rounded-md border border-input bg-surface px-2 text-caption text-ink-heading hover:border-ink-subtle">
          {meta.feeds.map((f) => <option key={f.key} value={f.key}>{f.label}</option>)}
        </select>
        <Button type="button" size="sm" variant="outline" disabled={probe.isPending || !url.trim()}
          onClick={() => probe.mutate({ feed, base_url: url.trim(), api_key: key || null, field_map: parseMap(map)[feed] ?? {} })}>
          {probe.isPending ? 'Testing…' : 'Test connection'}
        </Button>
        {saved2 && <span className="text-caption text-success-text">Saved.</span>}
      </div>

      {save.isError && <p role="alert" className="text-caption text-danger-text">{errorMessage(save.error)}</p>}
      {probe.isError && <p role="alert" className="text-caption text-danger-text">{errorMessage(probe.error)}</p>}
      {result && (
        <div role="status" className={`rounded-md border p-2.5 text-caption ${result.ok ? 'border-success-border bg-success-soft text-success-text' : 'border-danger-border bg-danger-soft text-danger-text'}`}>
          {result.error ? result.error : (
            <>
              <p>{result.rows} record(s) came back. {result.note}</p>
              {!!result.missing?.length && <p className="mt-1">Not found: {result.missing.join(', ')}.</p>}
              {result.sample && <p className="mt-1 font-mono text-caption">{Object.keys(result.sample).slice(0, 10).join(', ')}</p>}
            </>
          )}
        </div>
      )}
      <p className="text-caption text-ink-subtle">
        {saved.source === 'env' ? 'Currently taken from the server settings file.' :
          `Last changed by ${saved.updated_by ?? 'someone'}${saved.updated_at ? ` on ${new Date(saved.updated_at).toLocaleDateString()}` : ''}.`}
      </p>
    </form>
  );
}
