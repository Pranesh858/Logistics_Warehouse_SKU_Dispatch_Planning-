import { api } from '@/lib/api';
import type { ExportEntry, OutlookRow, Plan, PlanBrief, ReviewBody, Truck } from './types';

/** wh = narrow to one warehouse (admins and viewers). A planner's warehouse is fixed by the server. */
const scoped = (wh?: string | null) => (wh ? { warehouse_id: wh } : undefined);

export const dispatchApi = {
  current: (wh?: string | null) => api.get<Plan | null>('/dispatch/plans/current', scoped(wh)),
  plan: (id: number, wh?: string | null) => api.get<Plan>(`/dispatch/plans/${id}`, scoped(wh)),
  plans: () => api.get<PlanBrief[]>('/dispatch/plans'),
  outlook: (id: number, wh?: string | null) => api.get<OutlookRow[]>(`/dispatch/plans/${id}/outlook`, scoped(wh)),
  exports: (id: number, wh?: string | null) => api.get<ExportEntry[]>(`/dispatch/plans/${id}/exports`, scoped(wh)),
  recalculate: () => api.post<Plan | null>('/dispatch/plans/recalculate'),
  review: (id: number, orderId: string, body: ReviewBody) =>
    api.patch<Plan>(`/dispatch/plans/${id}/lines/${encodeURIComponent(orderId)}`, body),
  approve: (id: number, wh?: string | null) => api.post<Plan>(`/dispatch/plans/${id}/approve`, wh ? { warehouse_id: wh } : {}),
  retry: (id: number) => api.post<Plan>(`/dispatch/plans/${id}/exports/retry`),
  trucks: (wh?: string | null) => api.get<Truck[]>('/dispatch/trucks', scoped(wh)),
  /** Every warehouse that has trucks, whatever the page is narrowed to (used by the warehouse pickers). */
  warehouses: () => api.get<Truck[]>('/dispatch/trucks', { include_inactive: true }).then((t) => Array.from(new Set(t.map((x) => x.warehouse_id))).sort()),
  addTruck: (body: { name: string; warehouse_id: string; capacity_units: number }) => api.post<Truck>('/dispatch/trucks', body),
  editTruck: (id: number, body: { name?: string; capacity_units?: number; active?: boolean }) => api.patch<Truck>(`/dispatch/trucks/${id}`, body),
  removeTruck: (id: number) => api.delete<Truck>(`/dispatch/trucks/${id}`),
  moveToTruck: (planId: number, orderId: string, truckId: number | null) =>
    api.patch<Plan>(`/dispatch/plans/${planId}/lines/${encodeURIComponent(orderId)}/truck`, { truck_id: truckId }),
};
