import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useAuth } from '@/features/auth/store';
import { integrationsApi } from './api';

export const useIntegrationStatus = () => {
  const userId = useAuth((s) => s.user?.id);
  return useQuery({ queryKey: ['integrations', 'status', userId], queryFn: integrationsApi.status, enabled: userId !== undefined, refetchInterval: 15_000 });
};

export const usePurchaseOrders = () => {
  const userId = useAuth((s) => s.user?.id);
  return useQuery({ queryKey: ['integrations', 'po', userId], queryFn: integrationsApi.purchaseOrders, enabled: userId !== undefined });
};

/** After a stock, order or sales sync every plan and forecast number may have changed. */
const refreshAll = (qc: ReturnType<typeof useQueryClient>) => {
  qc.invalidateQueries({ queryKey: ['integrations'] });
  qc.invalidateQueries({ queryKey: ['forecast'] });
  qc.invalidateQueries({ queryKey: ['dispatch'] });
};

export function useSync() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: integrationsApi.sync, onSuccess: () => refreshAll(qc) });
}

export function useCreatePurchase() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: integrationsApi.createPurchase, onSuccess: () => qc.invalidateQueries({ queryKey: ['integrations'] }) });
}

export const usePending = () => {
  const userId = useAuth((s) => s.user?.id);
  return useQuery({ queryKey: ['integrations', 'pending', userId], queryFn: integrationsApi.pending, enabled: userId !== undefined });
};

export const useAudit = (enabled: boolean) =>
  useQuery({ queryKey: ['integrations', 'audit'], queryFn: integrationsApi.audit, enabled });

export function useSaveSystem() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ system, body }: { system: 'wms' | 'erp'; body: Parameters<typeof integrationsApi.saveSystem>[1] }) =>
      integrationsApi.saveSystem(system, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['integrations'] }),
  });
}

export const useTestConnection = () => useMutation({ mutationFn: integrationsApi.testConnection });

export function useConfirmAll() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: integrationsApi.confirmAll, onSuccess: () => refreshAll(qc) });
}

export function useRetryPurchase() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: integrationsApi.retryPurchase, onSuccess: () => qc.invalidateQueries({ queryKey: ['integrations'] }) });
}

/** Receiving a delivery changes what ordering asks for, so the forecast queries are refreshed too. */
export function useReceivePurchase() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: integrationsApi.receivePurchase,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['integrations'] }); qc.invalidateQueries({ queryKey: ['forecast'] }); },
  });
}
