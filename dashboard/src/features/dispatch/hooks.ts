import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useScope } from '@/features/auth/store';
import { dispatchApi } from './api';
import type { ReviewBody } from './types';

const KEY = ['dispatch'] as const;

export const useCurrentPlan = () => {
  const wh = useScope();
  return useQuery({ queryKey: [...KEY, 'current', wh], queryFn: () => dispatchApi.current(wh), refetchInterval: 30_000 });
};

export const usePlanHistory = () => useQuery({ queryKey: [...KEY, 'plans'], queryFn: dispatchApi.plans });

export const usePlan = (id?: number) => {
  const wh = useScope();
  return useQuery({ queryKey: [...KEY, 'plan', id, wh], queryFn: () => dispatchApi.plan(id as number, wh), enabled: id !== undefined });
};

export const useOutlook = (id?: number, enabled = true) => {
  const wh = useScope();
  return useQuery({ queryKey: [...KEY, 'outlook', id, wh], queryFn: () => dispatchApi.outlook(id as number, wh), enabled: enabled && id !== undefined });
};

export const useExportLog = (id?: number, enabled = true) => {
  const wh = useScope();
  return useQuery({ queryKey: [...KEY, 'exports', id, wh], queryFn: () => dispatchApi.exports(id as number, wh), enabled: enabled && id !== undefined });
};

export const useWarehouseList = () => useQuery({ queryKey: [...KEY, 'warehouses'], queryFn: dispatchApi.warehouses, staleTime: 5 * 60_000 });

function useInvalidate() {
  const qc = useQueryClient();
  return () => qc.invalidateQueries({ queryKey: KEY });
}

export function useReviewLine(planId: number) {
  const done = useInvalidate();
  return useMutation({
    mutationFn: ({ orderId, body }: { orderId: string; body: ReviewBody }) => dispatchApi.review(planId, orderId, body),
    onSuccess: done,
  });
}

export function useApprovePlan(planId: number) {
  const done = useInvalidate();
  const wh = useScope();
  return useMutation({ mutationFn: () => dispatchApi.approve(planId, wh), onSuccess: done });
}

export function useRetryExports(planId: number) {
  const done = useInvalidate();
  return useMutation({ mutationFn: () => dispatchApi.retry(planId), onSuccess: done });
}

export function useRecalculate() {
  const done = useInvalidate();
  return useMutation({ mutationFn: dispatchApi.recalculate, onSuccess: done });
}

export const useTrucks = () => {
  const wh = useScope();
  return useQuery({ queryKey: [...KEY, 'trucks', wh], queryFn: () => dispatchApi.trucks(wh) });
};

export function useAddTruck() {
  const done = useInvalidate();
  return useMutation({ mutationFn: dispatchApi.addTruck, onSuccess: done });
}

export function useEditTruck() {
  const done = useInvalidate();
  return useMutation({
    mutationFn: ({ id, body }: { id: number; body: { name?: string; capacity_units?: number; active?: boolean } }) => dispatchApi.editTruck(id, body),
    onSuccess: done,
  });
}

export function useRemoveTruck() {
  const done = useInvalidate();
  return useMutation({ mutationFn: dispatchApi.removeTruck, onSuccess: done });
}

export function useMoveToTruck(planId: number) {
  const done = useInvalidate();
  return useMutation({
    mutationFn: ({ orderId, truckId }: { orderId: string; truckId: number | null }) => dispatchApi.moveToTruck(planId, orderId, truckId),
    onSuccess: done,
  });
}
