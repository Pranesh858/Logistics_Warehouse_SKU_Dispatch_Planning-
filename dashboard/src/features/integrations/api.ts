import { api } from '@/lib/api';
import type { AuditEntry, FeedKey, IntegrationStatus, PendingConfirmations, PurchaseOrder, PurchaseRequest, SystemInput, SystemSettings, TestResult } from './types';

export const integrationsApi = {
  status: () => api.get<IntegrationStatus>('/integrations/status'),
  sync: (feed: 'inventory' | 'orders' | 'sales') =>
    api.post<{ feed: string; status: 'OK' | 'FAILED'; rows: number; message: string }>(`/integrations/sync/${feed}`),
  purchaseOrders: () => api.get<PurchaseOrder[]>('/integrations/purchase-orders'),
  createPurchase: (body: PurchaseRequest) => api.post<PurchaseOrder[]>('/integrations/purchase-orders', body),
  retryPurchase: (id: number) => api.post<PurchaseOrder>(`/integrations/purchase-orders/${id}/retry`),
  receivePurchase: (id: number) => api.post<PurchaseOrder>(`/integrations/purchase-orders/${id}/receive`),
  saveSystem: (system: 'wms' | 'erp', body: SystemInput) => api.put<SystemSettings>(`/integrations/settings/${system}`, body),
  testConnection: (body: { feed: string; base_url?: string; api_key?: string | null; field_map?: Record<string, string> }) =>
    api.post<TestResult>('/integrations/settings/test', body),
  pending: () => api.get<PendingConfirmations>('/integrations/confirmations/pending'),
  confirmAll: () => api.post<{ shipped: number; cancelled: number; units_released: number; message: string }>('/integrations/confirmations/all'),
  audit: () => api.get<AuditEntry[]>('/integrations/audit'),
};
