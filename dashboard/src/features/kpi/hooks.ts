import { useQuery } from '@tanstack/react-query';
import { useAuth } from '@/features/auth/store';
import { kpiApi } from './api';

// A planner gets their own warehouse from the server; the page's own warehouse picker handles the rest.
export const useAccuracy = () => {
  const userId = useAuth((s) => s.user?.id);
  return useQuery({ queryKey: ['kpi', 'accuracy', userId], queryFn: kpiApi.accuracy, staleTime: 10 * 60_000, enabled: userId !== undefined });
};
