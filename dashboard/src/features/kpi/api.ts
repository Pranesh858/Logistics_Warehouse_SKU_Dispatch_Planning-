import { api } from '@/lib/api';
import type { Accuracy } from './types';

export const kpiApi = { accuracy: () => api.get<Accuracy>('/forecast/accuracy') };
