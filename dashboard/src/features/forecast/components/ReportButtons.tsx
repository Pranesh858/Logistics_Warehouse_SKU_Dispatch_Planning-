'use client';

import { useState } from 'react';
import { Download } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { errorMessage } from '@/lib/api';
import { downloadReport } from '../api';
import type { ReportKind } from '../types';

/** One PDF for the key points, one Excel with every row. */
export function ReportButtons({ kind, days, safety, warehouse, pdfLabel = 'PDF', xlsxLabel = 'Excel' }: {
  kind: ReportKind; days?: number; safety?: boolean; warehouse?: string; pdfLabel?: string; xlsxLabel?: string;
}) {
  const [busy, setBusy] = useState<'pdf' | 'xlsx' | null>(null);
  const [error, setError] = useState('');

  const go = async (format: 'pdf' | 'xlsx') => {
    setBusy(format);
    setError('');
    try {
      await downloadReport(kind, format, { days, safety, warehouse_id: warehouse });
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="flex items-center gap-1.5">
      <Button variant="outline" size="sm" disabled={busy !== null} onClick={() => go('pdf')}>
        <Download className="h-3.5 w-3.5" aria-hidden="true" />{busy === 'pdf' ? 'Preparing…' : pdfLabel}
      </Button>
      <Button variant="outline" size="sm" disabled={busy !== null} onClick={() => go('xlsx')}>
        <Download className="h-3.5 w-3.5" aria-hidden="true" />{busy === 'xlsx' ? 'Preparing…' : xlsxLabel}
      </Button>
      {error && <span role="alert" className="text-caption text-danger-text">{error}</span>}
    </div>
  );
}
