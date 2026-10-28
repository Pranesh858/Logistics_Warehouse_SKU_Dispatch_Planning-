import { api } from '@/lib/api';
import type { Alert, AlertSummary, DeliveryTest } from './types';

const scoped = (wh?: string | null) => (wh ? { warehouse_id: wh } : undefined);

export const alertsApi = {
  list: (wh?: string | null, status?: string) =>
    api.get<Alert[]>('/alerts', { ...(scoped(wh) ?? {}), ...(status ? { status } : {}) }),
  summary: (wh?: string | null) => api.get<AlertSummary>('/alerts/summary', scoped(wh)),
  acknowledge: (id: number) => api.post<Alert>(`/alerts/${id}/acknowledge`),
  resolve: (id: number, note: string) => api.post<Alert>(`/alerts/${id}/resolve`, { note }),
  sweep: () => api.post<Record<string, unknown>>('/alerts/sweep'),
  testDelivery: () => api.post<DeliveryTest>('/alerts/test-delivery'),
};
