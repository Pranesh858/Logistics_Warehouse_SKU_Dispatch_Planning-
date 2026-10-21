import { api } from '@/lib/api';
import type { AuthUser, LoginResult, Role } from './types';

export const authApi = {
  login: (username: string, password: string) => api.post<LoginResult>('/auth/login', { username, password }),
  changePassword: (current_password: string, new_password: string) =>
    api.post<LoginResult>('/auth/change-password', { current_password, new_password }),
  users: () => api.get<AuthUser[]>('/users'),
  addUser: (body: { username: string; name: string; password: string; role: Role; warehouse_id?: string | null }) =>
    api.post<AuthUser>('/users', body),
  editUser: (id: number, body: { name?: string; password?: string; role?: Role; warehouse_id?: string | null; active?: boolean }) =>
    api.patch<AuthUser>(`/users/${id}`, body),
};
