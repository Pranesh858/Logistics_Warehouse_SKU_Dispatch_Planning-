import { api } from '@/lib/api';
import type { Plan } from '@/features/dispatch/types';
import type { NewOrder, StockCount, StockResult } from './types';

export const entryApi = {
  addOrders: (orders: NewOrder[]) => api.post<Plan>('/dispatch/orders', { orders }),
  setStock: (items: StockCount[], reason: string) => api.post<StockResult>('/integrations/stock', { items, reason }),
};
