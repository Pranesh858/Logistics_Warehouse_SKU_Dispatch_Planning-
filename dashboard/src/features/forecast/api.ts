import { api } from '@/lib/api';
import { apiClient } from '@/lib/axios';
import type { DatasetStatus, ExplainResult, ForecastRequest, ForecastResult, OrdersResult, ReportKind, SkuRow } from './types';

export const forecastApi = {
  skus: () => api.get<SkuRow[]>('/forecast/skus'),
  run: (body: ForecastRequest) => api.post<ForecastResult>('/forecast/run', body),
  explain: (product_id: number, warehouse_id: string, days: number) =>
    api.get<ExplainResult>('/forecast/explain', { product_id, warehouse_id, days }),
  orders: (days: number, safety: boolean, warehouse_id?: string) =>
    api.get<OrdersResult>('/forecast/orders', { days, safety, warehouse_id: warehouse_id || undefined }),
  datasetStatus: () => api.get<DatasetStatus>('/forecast/dataset/status'),
  datasetCheck: (file: File) => {
    const form = new FormData();
    form.append('file', file);
    return apiClient.post<DatasetStatus>('/api/v1/forecast/dataset/check', form, { headers: { 'Content-Type': 'multipart/form-data' } }).then((r) => r.data);
  },
  datasetApply: (force: boolean) => apiClient.post<DatasetStatus>(`/api/v1/forecast/dataset/apply?force=${force}`).then((r) => r.data),
  datasetDiscard: () => apiClient.delete<DatasetStatus>('/api/v1/forecast/dataset/check').then((r) => r.data),
};

/** Downloads a report the backend builds (PDF = key points, Excel = every row). */
export async function downloadReport(kind: ReportKind, format: 'pdf' | 'xlsx', params: { days?: number; safety?: boolean; warehouse_id?: string }) {
  const res = await apiClient.get<Blob>(`/api/v1/forecast/reports/${kind}`, {
    params: { format, days: params.days, safety: params.safety, warehouse_id: params.warehouse_id || undefined },
    responseType: 'blob',
  });
  const name = /filename="([^"]+)"/.exec(String(res.headers['content-disposition'] ?? ''))?.[1] ?? `${kind}.${format}`;
  const url = URL.createObjectURL(res.data);
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
