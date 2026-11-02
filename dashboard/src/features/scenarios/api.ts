import { api } from '@/lib/api';
import type { ScenarioIn, ScenarioResult } from './types';

export const scenariosApi = { run: (body: ScenarioIn) => api.post<ScenarioResult>('/scenarios/run', body) };
