import { QueryClient } from "@tanstack/react-query";

export function createQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        refetchOnWindowFocus: false,
        // HTTP retries live in the transport, where the actual method is known.
        // A query function may include a legacy import mutation, so replaying the
        // whole function here can duplicate POST/PUT side effects.
        retry: false,
      },
      mutations: {
        retry: false,
      },
    },
  });
}
