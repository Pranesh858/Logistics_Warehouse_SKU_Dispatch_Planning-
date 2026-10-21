import type { Metadata } from 'next';
import './globals.css';
import { AuthGate } from '@/features/auth/components/AuthGate';
import { QueryProvider } from '@/components/providers/QueryProvider';

export const metadata: Metadata = {
  title: 'Dispatch Planner',
  description: 'Forecasts SKU demand per warehouse, recommends which orders to dispatch and on which trucks, and sends the plan to the WMS once a planner approves it.',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <QueryProvider>
          <AuthGate>{children}</AuthGate>
        </QueryProvider>
      </body>
    </html>
  );
}
