import { QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { ApiError, basePath } from "./api/client";
import App from "./App";
import "./index.css";
import { useUi } from "./store/ui";

document.documentElement.dataset.theme = useUi.getState().theme;

// A page restored from the back/forward cache would show the screen as it was before sign-out: reload instead,
// so the current session decides what is shown.
window.addEventListener("pageshow", (e) => {
  if (e.persisted) window.location.reload();
});

const queryClient = new QueryClient({
  // Any 401 means the session ended (sign-out elsewhere, expiry, revocation): re-check it so sign-in shows at once.
  queryCache: new QueryCache({
    onError: (error, query) => {
      if (error instanceof ApiError && error.status === 401 && query.queryKey[0] !== "auth") {
        void queryClient.invalidateQueries({ queryKey: ["auth"] });
      }
    },
  }),
  defaultOptions: {
    queries: {
      staleTime: 15_000,
      retry: (count, error) => !(error instanceof ApiError && error.status >= 400 && error.status < 500) && count < 2,
      refetchOnWindowFocus: false,
    },
  },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter basename={basePath || undefined}>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
