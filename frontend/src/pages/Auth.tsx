import { useQueryClient } from "@tanstack/react-query";
import { type FormEvent, type ReactNode, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ApiError, isDemo, post } from "../api/client";
import type { Body } from "../api/contract";
import { Button, ErrorState, HelpLink, Loading, TextField } from "../components/ui";
import { useApi } from "../hooks/useApi";
import { CREDIT } from "../lib/brand";

const HIGHLIGHTS = [
  { title: "Research with evidence", text: "Library passages with exact citations, market data and portfolio context. An optional local model can help." },
  { title: "Decisions you can replay", text: "The evidence you decided on is frozen and hashed, so you can replay and review any decision later." },
  { title: "Orders stay under your control", text: "Preview, approve, submit and reconcile. The broker is a built-in Mock, and live trading is off." },
  { title: "Private by default", text: "Runs on this computer and keeps working offline after setup." },
];

function AuthFrame({ title, subtitle, children }: { title: string; subtitle?: ReactNode; children: ReactNode }) {
  return (
    <main id="main" className="flex min-h-full items-center justify-center px-4 py-8 sm:py-12">
      <div className="grid w-full max-w-5xl grid-cols-1 items-center gap-8 lg:grid-cols-[1fr_420px] lg:gap-14">
        <section aria-label="About Investment DecisionOps AI" className="order-2 lg:order-1">
          <div className="hidden items-center gap-2.5 lg:flex">
            <img src="/favicon.svg" alt="" className="h-8 w-8" />
            <span className="text-lg font-semibold tracking-tight">Investment DecisionOps AI</span>
          </div>
          <p className="text-2xl font-semibold leading-tight tracking-tight lg:mt-6 lg:text-3xl">
            Make investment decisions you can explain later.
          </p>
          <p className="mt-3 max-w-xl text-sm leading-relaxed text-muted lg:text-base">
            A private workspace that researches your question, freezes the evidence you decided on and keeps every order
            behind your approval. AI analyses and proposes; you decide.
          </p>
          <ul className="mt-6 grid gap-3 sm:grid-cols-2">
            {HIGHLIGHTS.map((h) => (
              <li key={h.title} className="rounded-lg border border-line bg-surface/60 p-3.5">
                <p className="text-sm font-semibold">{h.title}</p>
                <p className="mt-1 text-xs leading-relaxed text-muted">{h.text}</p>
              </li>
            ))}
          </ul>
        </section>

        <div className="order-1 w-full lg:order-2">
          <div className="mb-4 flex items-center justify-center gap-2.5 lg:hidden">
            <img src="/favicon.svg" alt="" className="h-7 w-7" />
            <span className="font-semibold tracking-tight">Investment DecisionOps AI</span>
          </div>
          <div className="rounded-xl border border-line bg-surface p-6 shadow-lg shadow-black/10 sm:p-7">
            {isDemo && (
              <p className="mb-4 inline-flex rounded border border-warn/40 bg-warn/10 px-2 py-0.5 text-[11px] font-medium uppercase tracking-wide text-warn">
                Read-only demo · synthetic data
              </p>
            )}
            <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
            {subtitle && <p className="mt-1.5 text-sm text-muted">{subtitle}</p>}
            <div className="mt-6">{children}</div>
            <p className="mt-6 border-t border-line pt-4 text-xs text-muted">
              {isDemo ? (
                <a className="text-accent underline" href="/">Back to your workspace</a>
              ) : (
                <>Want to look around first? <a className="text-accent underline" href="/demo/">Enter the read-only demo</a> (synthetic data).</>
              )}
            </p>
          </div>
          <p className="mt-4 text-center text-[11px] text-muted">{CREDIT}</p>
        </div>
      </div>
    </main>
  );
}

export function LoginPage() {
  const qc = useQueryClient();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [needCode, setNeedCode] = useState(false);
  const [useRecovery, setUseRecovery] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await post("/auth/login", {
        email, password,
        totp_code: needCode && !useRecovery ? code : undefined,
        recovery_code: needCode && useRecovery ? code : undefined,
      } satisfies Body<"LoginIn">);
      await qc.invalidateQueries({ queryKey: ["auth"] });
    } catch (err) {
      if (err instanceof ApiError && err.code === "totp_required") setNeedCode(true);
      else setError(err as ApiError);
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthFrame
      title={isDemo ? "Sign in to the demo" : "Sign in"}
      subtitle={isDemo ? "Explore a sample workspace. Nothing here is real, and nothing can be changed. The demo account is listed in the README." : "Welcome back to your private workspace."}
    >
      <form onSubmit={submit} className="flex flex-col gap-3" noValidate>
        <TextField label="Email" type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required autoFocus />
        <TextField label="Password" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
        {needCode && (
          <>
            <TextField
              label={useRecovery ? "Recovery code" : "Authenticator code"}
              inputMode={useRecovery ? "text" : "numeric"}
              autoComplete="one-time-code"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              autoFocus
            />
            <button type="button" className="self-start text-xs text-accent hover:underline" onClick={() => setUseRecovery(!useRecovery)}>
              {useRecovery ? "Use authenticator code instead" : "Use a recovery code instead"}
            </button>
          </>
        )}
        <ErrorState error={error} />
        <Button type="submit" variant="primary" busy={busy}>
          Sign in
        </Button>
        {!isDemo && (
          <p className="text-xs text-muted">
            Forgot your password? <HelpLink slug="first-run-and-recovery" label="Recovery options" />
          </p>
        )}
      </form>
    </AuthFrame>
  );
}

const ZONES = ["Asia/Jerusalem", "Europe/London", "Europe/Berlin", "America/New_York", "Asia/Tokyo", "Asia/Shanghai", "UTC"];

export function SetupPage() {
  const qc = useQueryClient();
  const [form, setForm] = useState({ setup_token: "", email: "", display_name: "", password: "", confirm: "", timezone: "Asia/Jerusalem" });
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });
  const mismatch = form.confirm.length > 0 && form.confirm !== form.password;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (mismatch) return;
    setBusy(true);
    setError(null);
    try {
      const { confirm: _c, ...body } = form;
      void _c;
      await post("/auth/setup", body satisfies Body<"SetupIn">);
      await qc.invalidateQueries({ queryKey: ["auth"] });
    } catch (err) {
      setError(err as ApiError);
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthFrame
      title="Set up your workspace"
      subtitle={
        <>
          Paste the one-time setup token printed in the API logs (<code>docker compose logs api</code>). It is valid for 24 hours and works once.
        </>
      }
    >
      <form onSubmit={submit} className="flex flex-col gap-3">
        <TextField label="Setup token" value={form.setup_token} onChange={set("setup_token")} required autoFocus autoComplete="off" />
        <TextField label="Your name" value={form.display_name} onChange={set("display_name")} required autoComplete="name" />
        <TextField label="Email" type="email" value={form.email} onChange={set("email")} required autoComplete="username" />
        <TextField label="Password" type="password" value={form.password} onChange={set("password")} required autoComplete="new-password" hint="At least 12 characters. A passphrase works well." />
        <TextField label="Confirm password" type="password" value={form.confirm} onChange={set("confirm")} required autoComplete="new-password" error={mismatch ? "Passwords do not match." : undefined} />
        <div className="flex flex-col gap-1">
          <label htmlFor="tz" className="text-xs font-medium text-muted">
            Home timezone
          </label>
          <select id="tz" value={form.timezone} onChange={set("timezone")} className="rounded-md border border-line bg-surface-2 px-2.5 py-1.5 text-sm">
            {ZONES.map((z) => (
              <option key={z}>{z}</option>
            ))}
          </select>
        </div>
        <ErrorState error={error} />
        <Button type="submit" variant="primary" busy={busy}>
          Create owner account
        </Button>
        <p className="text-xs text-muted">
          You start in <strong>Mock mode</strong> with a synthetic portfolio. <HelpLink slug="first-run-and-recovery" label="First-run guide" />
        </p>
      </form>
    </AuthFrame>
  );
}

export function AcceptInvitePage() {
  const { token = "" } = useParams();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const info = useApi<{ email: string; display_name: string; timezone: string }>(["invite", token], `/invitations/accept/${token}`, { retry: false });
  const [password, setPassword] = useState("");
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  if (info.isLoading) return <Loading />;
  if (info.error)
    return (
      <AuthFrame title="Invitation">
        <ErrorState error={info.error} />
        <Link to="/" className="mt-3 inline-block text-sm text-accent">
          Go to sign in
        </Link>
      </AuthFrame>
    );
  return (
    <AuthFrame title={`Welcome, ${info.data!.display_name}`} subtitle={`You were invited as a collaborator (${info.data!.email}). You will see only what the owner shares with you.`}>
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          setError(null);
          try {
            await post("/invitations/accept", { token, password } satisfies Body<"AcceptIn">);
            await qc.invalidateQueries({ queryKey: ["auth"] });
            navigate("/shared");
          } catch (err) {
            setError(err as ApiError);
          } finally {
            setBusy(false);
          }
        }}
        className="flex flex-col gap-3"
      >
        <TextField label="Choose a password" type="password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} hint="At least 12 characters." />
        <ErrorState error={error} />
        <Button type="submit" variant="primary" busy={busy}>
          Accept invitation
        </Button>
      </form>
    </AuthFrame>
  );
}
