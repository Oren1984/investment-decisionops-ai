import { useQueryClient } from "@tanstack/react-query";
import type { Body } from "../../api/contract";
import { type ReactNode, useState } from "react";
import { Link, NavLink, useLocation, useNavigate } from "react-router-dom";
import { isDemo, post } from "../../api/client";
import { signOut } from "../../api/session";
import type { BrokerInfo, Feed, Me, Role } from "../../api/types";
import { useApi, useAction } from "../../hooks/useApi";
import { useLiveUpdates } from "../../hooks/useLive";
import { CREDIT } from "../../lib/brand";
import { fmtTime } from "../../lib/format";
import { useStepUp, useUi } from "../../store/ui";
import { Badge, Button, Dialog, TextField, cx } from "../ui";
import { ClockStrip } from "./ClockStrip";
import { WorkflowBar } from "./WorkflowBar";

const OWNER_NAV = [
  { to: "/", label: "Overview", icon: "◧" },
  { to: "/markets", label: "Markets", icon: "◷" },
  { to: "/portfolio", label: "Portfolio", icon: "◔" },
  { to: "/decisions", label: "Decisions", icon: "◇" },
  { to: "/orders", label: "Orders", icon: "⇄" },
  { to: "/collaboration", label: "Collaboration", icon: "◎" },
  { to: "/library", label: "Library", icon: "▤" },
  { to: "/settings", label: "Settings", icon: "⚙" },
  { to: "/help", label: "Help", icon: "?" },
];
const COLLAB_NAV = [
  { to: "/shared", label: "Shared with me", icon: "◎" },
  { to: "/settings", label: "My account", icon: "⚙" },
  { to: "/help", label: "Help", icon: "?" },
];

export function AppShell({ role, user, children }: { role: Role; user: Me | null; children: ReactNode }) {
  const { navOpen, setNavOpen, theme, setTheme } = useUi();
  const location = useLocation();
  const isOwnerView = role === "owner" || role === "demo";
  useLiveUpdates(true);
  const nav = isOwnerView ? OWNER_NAV : COLLAB_NAV;
  const showWorkflow = isOwnerView && !/^\/decisions\/[^/]+/.test(location.pathname) && !location.pathname.startsWith("/help");

  return (
    <div className="flex min-h-full flex-col">
      <a href="#main" className="skip-link">
        Skip to content
      </a>
      {isDemo && (
        <div className="border-b border-warn/40 bg-warn/10 px-4 py-1.5 text-center text-xs text-fg" role="note">
          <strong>Read-only demo</strong> with synthetic data and simulated execution. Nothing here is real, and nothing can be changed.
        </div>
      )}
      <header className="sticky top-0 z-30 border-b border-line bg-bg/95 backdrop-blur">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2 px-3 py-2 md:px-4">
          <button className="rounded p-1.5 text-muted hover:text-fg lg:hidden" aria-label="Open navigation" aria-expanded={navOpen} onClick={() => setNavOpen(!navOpen)}>
            ☰
          </button>
          <Link to="/" className="flex items-center gap-2 font-semibold tracking-tight">
            <img src="/favicon.svg" alt="" className="h-6 w-6" />
            <span className="hidden sm:inline">DecisionOps</span>
          </Link>
          {isOwnerView && <ModeAndFreshness />}
          <div className="ml-auto flex flex-wrap items-center justify-end gap-2">
            {role === "owner" && <StopControl />}
            <button className="rounded border border-line px-2 py-1 text-xs text-muted hover:text-fg" onClick={() => setTheme(theme === "dark" ? "light" : "dark")} aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}>
              <span aria-hidden>{theme === "dark" ? "☀" : "☾"}</span>
              <span className="hidden sm:inline"> {theme === "dark" ? "Light" : "Dark"}</span>
            </button>
            {!isDemo && user && <UserMenu user={user} />}
            {isDemo && <SignOutButton label="Sign out of demo" title={user?.email} />}
          </div>
        </div>
        <ClockStrip compact={!isOwnerView} />
      </header>
      <div className="flex flex-1">
        <nav
          aria-label="Main"
          className={cx(
            "fixed inset-y-0 left-0 z-20 w-52 shrink-0 border-r border-line bg-surface pt-28 transition-transform lg:static lg:translate-x-0 lg:pt-3",
            navOpen ? "translate-x-0" : "-translate-x-full",
          )}
        >
          <ul className="flex flex-col gap-0.5 px-2">
            {nav.map((n) => (
              <li key={n.to}>
                <NavLink
                  to={n.to}
                  end={n.to === "/"}
                  onClick={() => setNavOpen(false)}
                  className={({ isActive }) =>
                    cx("flex items-center gap-2.5 rounded-md px-3 py-2 text-sm", isActive ? "bg-surface-2 font-medium text-fg" : "text-muted hover:bg-surface-2 hover:text-fg")
                  }
                >
                  <span aria-hidden className="w-4 text-center text-xs">
                    {n.icon}
                  </span>
                  {n.label}
                </NavLink>
              </li>
            ))}
          </ul>
          <p className="mt-6 px-5 text-[11px] leading-snug text-muted">
            {CREDIT}
          </p>
        </nav>
        {navOpen && <div className="fixed inset-0 z-10 bg-black/40 lg:hidden" onClick={() => setNavOpen(false)} aria-hidden />}
        <div className="flex min-w-0 flex-1 flex-col">
          {showWorkflow && <WorkflowBar />}
          <main id="main" className="mx-auto w-full max-w-[1500px] flex-1 px-3 py-4 md:px-6">
            {children}
          </main>
        </div>
      </div>
      <StepUpDialog />
    </div>
  );
}

function ModeAndFreshness() {
  const broker = useApi<BrokerInfo>(["broker"], "/orders/broker", { refetchInterval: 30_000 });
  const feeds = useApi<Feed[]>(["feeds"], "/markets/feeds", { refetchInterval: 30_000 });
  const mode = (broker.data?.mode ?? "mock").toUpperCase();
  const quotes = feeds.data?.find((f) => f.key === "mock_quotes");
  return (
    <div className="flex items-center gap-2">
      <Badge tone={mode === "LIVE" ? "bad" : mode === "PAPER" ? "accent" : "warn"} title="Trading mode. Mock = simulated broker; nothing reaches a real market.">
        {mode}
        {broker.data?.connection.account_id ? <span className="normal-case tracking-normal">· {broker.data.connection.account_id}</span> : null}
      </Badge>
      {quotes && (
        <Badge tone={quotes.state === "fresh" ? "simulated" : "bad"} title="Market data freshness">
          {quotes.state === "fresh" ? "Synthetic data" : `Stale since ${fmtTime(quotes.stale_since ?? quotes.last_success_at)}`}
        </Badge>
      )}
      {broker.data?.stop.engaged && <Badge tone="bad">Stop engaged</Badge>}
    </div>
  );
}

function StopControl() {
  const broker = useApi<BrokerInfo>(["broker"], "/orders/broker");
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const engaged = broker.data?.stop.engaged ?? false;
  const action = useAction<Body<"StopIn">>("POST", "/orders/stop", { invalidate: [["broker"]], stepUp: true });
  return (
    <>
      <Button size="sm" variant={engaged ? "secondary" : "danger"} onClick={() => setOpen(true)} aria-label={engaged ? "Release stop" : "Engage stop"}>
        {engaged ? "■ Stop engaged" : "■ Stop"}
      </Button>
      <Dialog
        open={open}
        onOpenChange={setOpen}
        title={engaged ? "Release the stop?" : "Engage the stop?"}
        description="Stop blocks new orders and agent actions. It does not reverse fills and does not cancel orders the broker has already accepted. Use “Cancel open orders” on the Orders page for that."
      >
        {!engaged && <TextField label="Reason (optional)" value={reason} onChange={(e) => setReason(e.target.value)} />}
        {engaged && <p className="text-sm text-muted">Releasing requires you to confirm your password.</p>}
        {action.error && <p className="mt-2 text-sm text-bad">{action.error.message}</p>}
        <div className="mt-4 flex justify-end gap-2">
          <Button onClick={() => setOpen(false)}>Keep as is</Button>
          <Button
            variant={engaged ? "primary" : "danger"}
            busy={action.isPending}
            onClick={() => action.mutate({ engaged: !engaged, reason: reason || undefined }, { onSuccess: () => setOpen(false) })}
          >
            {engaged ? "Release stop" : "Engage stop now"}
          </Button>
        </div>
      </Dialog>
    </>
  );
}

function UserMenu({ user }: { user: Me }) {
  return (
    <div className="flex items-center gap-2">
      <span className="hidden text-xs text-muted md:inline" title={user.email}>
        {user.display_name} · {user.role}
      </span>
      <SignOutButton label="Sign out" />
    </div>
  );
}

/** Ends the session, clears cached data and shows sign-in at once; replace keeps the private page out of history. */
function SignOutButton({ label, title }: { label: string; title?: string }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  return (
    <Button
      size="sm"
      busy={busy}
      title={title}
      onClick={async () => {
        setBusy(true);
        try {
          await signOut(qc);
        } catch {
          /* the client is signed out regardless; the server session also expires on its own */
        } finally {
          navigate("/", { replace: true });
        }
      }}
    >
      {label}
    </Button>
  );
}

function StepUpDialog() {
  const { open, finish } = useStepUp();
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      await post("/auth/step-up", { password, totp_code: code || undefined } satisfies Body<"StepUpIn">);
      setPassword("");
      setCode("");
      finish(true);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog open={open} onOpenChange={(o) => !o && finish(false)} title="Confirm it's you" description="Approvals and sensitive settings need a fresh confirmation (valid for 5 minutes).">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
        className="flex flex-col gap-3"
      >
        <TextField label="Password" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} autoFocus />
        <TextField label="Authenticator code (if enabled)" inputMode="numeric" value={code} onChange={(e) => setCode(e.target.value)} />
        {error && <p className="text-sm text-bad" role="alert">{error}</p>}
        <div className="flex justify-end gap-2">
          <Button type="button" onClick={() => finish(false)}>
            Cancel
          </Button>
          <Button type="submit" variant="primary" busy={busy}>
            Confirm
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
