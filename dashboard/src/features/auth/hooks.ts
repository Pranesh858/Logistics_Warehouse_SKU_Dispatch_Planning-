import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { authApi } from './api';

export const useUsers = () => useQuery({ queryKey: ['users'], queryFn: authApi.users });

export function useAddUser() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: authApi.addUser, onSuccess: () => qc.invalidateQueries({ queryKey: ['users'] }) });
}

export function useEditUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: number; body: Parameters<typeof authApi.editUser>[1] }) => authApi.editUser(id, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['users'] }),
  });
}
