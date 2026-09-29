import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AuthError } from '@/lib/apiClient';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: (failureCount, error) => !(error instanceof AuthError) && failureCount < 2,
      refetchOnWindowFocus: false,
    },
  },
});

export function AppProviders({ children }) {
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}
