import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useAuth } from '@/features/auth/store';
import { forecastApi } from './api';

export const useSkus = () => useQuery({ queryKey: ['forecast', 'skus'], queryFn: forecastApi.skus, staleTime: 5 * 60_000 });

export const useRunForecast = () => useMutation({ mutationFn: forecastApi.run });

export const useExplain = (product_id?: number, warehouse_id?: string, days = 7) =>
  useQuery({
    queryKey: ['forecast', 'explain', product_id, warehouse_id, days],
    queryFn: () => forecastApi.explain(product_id as number, warehouse_id as string, days),
    enabled: product_id !== undefined && !!warehouse_id,
  });

/** Units to order. The server limits a planner to their own warehouse. */
export const useOrders = (days: number, safety: boolean, warehouse_id?: string, enabled = true) => {
  const userId = useAuth((s) => s.user?.id);
  return useQuery({
    queryKey: ['forecast', 'orders', userId, days, safety, warehouse_id ?? ''],
    queryFn: () => forecastApi.orders(days, safety, warehouse_id),
    staleTime: 5 * 60_000,
    enabled,
  });
};

export const useDatasetStatus = (enabled: boolean) =>
  useQuery({
    queryKey: ['forecast', 'dataset'],
    queryFn: forecastApi.datasetStatus,
    enabled,
    refetchInterval: (q) => (q.state.data?.state === 'running' ? 2000 : false),
  });

export function useDatasetActions() {
  const qc = useQueryClient();
  const put = (s: unknown) => qc.setQueryData(['forecast', 'dataset'], s);
  return {
    check: useMutation({ mutationFn: forecastApi.datasetCheck, onSuccess: put }),
    apply: useMutation({ mutationFn: forecastApi.datasetApply, onSuccess: put }),
    retrain: useMutation({ mutationFn: forecastApi.datasetRetrain, onSuccess: put }),
    discard: useMutation({ mutationFn: forecastApi.datasetDiscard, onSuccess: put }),
    // after a retrain every forecast-based number is stale
    refreshAll: () => qc.invalidateQueries({ queryKey: ['forecast'] }),
  };
}
