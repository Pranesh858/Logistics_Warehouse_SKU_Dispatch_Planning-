import { api } from '@/lib/api';
import type { Accuracy, ServiceKpis } from './types';

export const kpiApi = {
  accuracy: () => api.get<Accuracy>('/forecast/accuracy'),
  service: (warehouse_id?: string) => api.get<ServiceKpis>('/kpis', { warehouse_id: warehouse_id || undefined }),
};
