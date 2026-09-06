import { QueryClient } from "@tanstack/react-query";

export function createQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        refetchOnWindowFocus: false,
        // HTTP retries live in the transport, where the actual method is known.
        // Keep cache-level replay disabled so requests are never duplicated here.
        retry: false,
      },
      mutations: {
        retry: false,
      },
    },
  });
}
