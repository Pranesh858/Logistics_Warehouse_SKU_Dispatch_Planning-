'use client';

import { useState } from 'react';
import { Download } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { errorMessage } from '@/lib/api';
import { downloadReport } from '../api';
import type { ReportKind } from '../types';

/** One PDF (the key points) and one Excel file (every row) for a report. */
export function ReportButtons({ kind, days, safety, warehouse, pdfLabel = 'PDF summary', xlsxLabel = 'Excel list' }: {
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
    <div className="flex flex-wrap items-center gap-2">
      <Button variant="outline" size="sm" disabled={busy !== null} onClick={() => go('pdf')}>
        <Download className="mr-1.5 h-4 w-4" aria-hidden="true" />{busy === 'pdf' ? 'Preparing…' : pdfLabel}
      </Button>
      <Button variant="outline" size="sm" disabled={busy !== null} onClick={() => go('xlsx')}>
        <Download className="mr-1.5 h-4 w-4" aria-hidden="true" />{busy === 'xlsx' ? 'Preparing…' : xlsxLabel}
      </Button>
      {error && <span role="alert" className="text-body-sm text-danger-text">{error}</span>}
    </div>
  );
}
