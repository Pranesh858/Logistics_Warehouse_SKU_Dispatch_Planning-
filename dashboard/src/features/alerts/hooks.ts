import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useScope } from '@/features/auth/store';
import { alertsApi } from './api';

const KEY = ['alerts'] as const;

/** The badge. Polled, because an alert nobody is told about is just a database row. */
export const useAlertSummary = () => {
  const wh = useScope();
  return useQuery({ queryKey: [...KEY, 'summary', wh], queryFn: () => alertsApi.summary(wh), refetchInterval: 60_000 });
};

export const useAlerts = (status?: string) => {
  const wh = useScope();
  return useQuery({ queryKey: [...KEY, 'list', wh, status ?? 'live'], queryFn: () => alertsApi.list(wh, status), refetchInterval: 60_000 });
};

function useInvalidate() {
  const qc = useQueryClient();
  return () => qc.invalidateQueries({ queryKey: KEY });
}

export function useAcknowledge() {
  const done = useInvalidate();
  return useMutation({ mutationFn: alertsApi.acknowledge, onSuccess: done });
}

export function useResolve() {
  const done = useInvalidate();
  return useMutation({
    mutationFn: ({ id, note }: { id: number; note: string }) => alertsApi.resolve(id, note),
    onSuccess: done,
  });
}

export function useSweep() {
  const done = useInvalidate();
  return useMutation({ mutationFn: alertsApi.sweep, onSuccess: done });
}

export function useTestDelivery() {
  return useMutation({ mutationFn: alertsApi.testDelivery });
}
