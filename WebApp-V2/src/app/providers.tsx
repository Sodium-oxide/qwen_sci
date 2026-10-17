import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { ApiError } from "../shared/api/http";

export const queryClient = new QueryClient({defaultOptions: {
  queries: {staleTime: 10_000, retry: (count, error) => count < 2 && (!(error instanceof ApiError) || (error.status >= 500 && error.code !== "INVALID_RESPONSE")), refetchOnWindowFocus: true},
  mutations: {retry: false},
}});
export function Providers({children}: {children: ReactNode}) {return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;}
