import axios from 'axios';
import { useAuth } from '@/features/auth/store';

export const apiClient = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000',
  headers: { 'Content-Type': 'application/json' },
});

// Every call carries the signed-in person's token.
apiClient.interceptors.request.use((config) => {
  const token = useAuth.getState().token;
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

// A rejected or expired token sends the person back to the sign-in page. (A wrong password on the sign-in form is not that.)
apiClient.interceptors.response.use(
  (res) => res,
  (err) => {
    const isLogin = String(err.config?.url ?? '').includes('/auth/login');
    if (err.response?.status === 401 && !isLogin && typeof window !== 'undefined') {
      useAuth.getState().signOut();
      if (window.location.pathname !== '/login') window.location.assign('/login?expired=1');
    }
    return Promise.reject(err);
  },
);
