import axios from 'axios';
import { apiClient } from '@/lib/axios';

/** All backend routes live under /api/v1. */
export const api = {
  get: <T,>(url: string, params?: object) => apiClient.get<T>(`/api/v1${url}`, { params }).then((r) => r.data),
  post: <T,>(url: string, body?: object) => apiClient.post<T>(`/api/v1${url}`, body).then((r) => r.data),
  patch: <T,>(url: string, body?: object) => apiClient.patch<T>(`/api/v1${url}`, body).then((r) => r.data),
  put: <T,>(url: string, body?: object) => apiClient.put<T>(`/api/v1${url}`, body).then((r) => r.data),
  delete: <T,>(url: string) => apiClient.delete<T>(`/api/v1${url}`).then((r) => r.data),
};

/** Pulls the backend's `detail` message out of an axios error so the UI can show it as-is. */
export function errorMessage(err: unknown): string {
  if (axios.isAxiosError(err)) {
    const detail = err.response?.data?.detail;
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail)) return detail.map((d) => d.msg).join('; ');
    if (!err.response) return 'Cannot reach the backend. Check that it is running and NEXT_PUBLIC_API_URL is correct.';
    if (err.response.status >= 500) return `The server ran into an error (HTTP ${err.response.status}). Try again; if it keeps happening, check the backend log.`;
  }
  return err instanceof Error ? err.message : 'Something went wrong';
}
