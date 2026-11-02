import { useQuery } from '@tanstack/react-query';
import { useAuth, useScope } from '@/features/auth/store';
import { kpiApi } from './api';

// Under 'dispatch', so approving, generating a plan or a sync refreshes the figures with the plan they come from.
export const useServiceKpis = () => {
  const wh = useScope();
  return useQuery({ queryKey: ['dispatch', 'kpis', wh], queryFn: () => kpiApi.service(wh ?? undefined), refetchInterval: 60_000 });
};

// A planner gets their own warehouse from the server; the page's own warehouse picker handles the rest.
export const useAccuracy = () => {
  const userId = useAuth((s) => s.user?.id);
  return useQuery({ queryKey: ['kpi', 'accuracy', userId], queryFn: kpiApi.accuracy, staleTime: 10 * 60_000, enabled: userId !== undefined });
};
