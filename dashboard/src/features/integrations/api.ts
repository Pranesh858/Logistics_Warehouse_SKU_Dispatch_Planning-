import { api } from '@/lib/api';
import type { FeedKey, IntegrationStatus, PurchaseOrder, PurchaseRequest } from './types';

export const integrationsApi = {
  status: () => api.get<IntegrationStatus>('/integrations/status'),
  sync: (feed: Exclude<FeedKey, 'purchasing'>) =>
    api.post<{ feed: string; status: 'OK' | 'FAILED'; rows: number; message: string }>(`/integrations/sync/${feed}`),
  purchaseOrders: () => api.get<PurchaseOrder[]>('/integrations/purchase-orders'),
  createPurchase: (body: PurchaseRequest) => api.post<PurchaseOrder[]>('/integrations/purchase-orders', body),
  retryPurchase: (id: number) => api.post<PurchaseOrder>(`/integrations/purchase-orders/${id}/retry`),
};
