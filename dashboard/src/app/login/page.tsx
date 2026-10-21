import { Suspense } from 'react';
import { LoginPage } from '@/features/auth/components/LoginPage';

export default function Page() {
  return <Suspense><LoginPage /></Suspense>;
}
