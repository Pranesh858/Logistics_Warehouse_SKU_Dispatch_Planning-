import { useMutation, useQueryClient } from '@tanstack/react-query';
import { entryApi } from './api';
import type { NewOrder, StockCount } from './types';

/** Typing something in changes the plan, the stock shown everywhere and the alerts, so all of them are refetched. */
function useRefreshEverything() {
  const qc = useQueryClient();
  return () => Promise.all(
    ['dispatch', 'forecast', 'alerts', 'integrations', 'ordering'].map((k) => qc.invalidateQueries({ queryKey: [k] })),
  );
}

export function useAddOrder() {
  const done = useRefreshEverything();
  return useMutation({ mutationFn: (order: NewOrder) => entryApi.addOrders([order]), onSuccess: done });
}

export function useSetStock() {
  const done = useRefreshEverything();
  return useMutation({
    mutationFn: ({ item, reason }: { item: StockCount; reason: string }) => entryApi.setStock([item], reason),
    onSuccess: done,
  });
}
