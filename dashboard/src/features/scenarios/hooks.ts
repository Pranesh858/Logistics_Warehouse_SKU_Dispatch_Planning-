import { useMutation } from '@tanstack/react-query';
import { scenariosApi } from './api';

// Nothing to refresh afterwards: a scenario changes nothing stored.
export const useRunScenario = () => useMutation({ mutationFn: scenariosApi.run });
