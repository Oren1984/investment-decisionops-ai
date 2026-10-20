import { create } from "zustand";

/** UI preferences only (server state lives in TanStack Query). */
type Theme = "dark" | "light";

function readTheme(): Theme {
  try {
    const t = localStorage.getItem("dops.theme");
    if (t === "dark" || t === "light") return t;
  } catch {
    /* storage unavailable */
  }
  return window.matchMedia?.("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

function readVenue(): string {
  try {
    return localStorage.getItem("dops.venue") ?? "XNYS";
  } catch {
    return "XNYS";
  }
}

type UiState = {
  theme: Theme;
  venue: string;
  navOpen: boolean;
  setTheme: (t: Theme) => void;
  setVenue: (v: string) => void;
  setNavOpen: (o: boolean) => void;
};

export const useUi = create<UiState>((set) => ({
  theme: readTheme(),
  venue: readVenue(),
  navOpen: false,
  setTheme: (theme) => {
    try {
      localStorage.setItem("dops.theme", theme);
    } catch {
      /* ignore */
    }
    document.documentElement.dataset.theme = theme;
    set({ theme });
  },
  setVenue: (venue) => {
    try {
      localStorage.setItem("dops.venue", venue);
    } catch {
      /* ignore */
    }
    set({ venue });
  },
  setNavOpen: (navOpen) => set({ navOpen }),
}));

/** Step-up (re-authentication) dialog coordination. */
type StepUpState = {
  open: boolean;
  resolve?: (ok: boolean) => void;
  request: () => Promise<boolean>;
  finish: (ok: boolean) => void;
};

export const useStepUp = create<StepUpState>((set, get) => ({
  open: false,
  request: () => new Promise<boolean>((resolve) => set({ open: true, resolve })),
  finish: (ok) => {
    get().resolve?.(ok);
    set({ open: false, resolve: undefined });
  },
}));
