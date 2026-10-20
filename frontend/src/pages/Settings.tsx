import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import type { Body } from "../api/contract";
import { Link } from "react-router-dom";
import { apiBase, isDemo, post } from "../api/client";
import { clearClientSession } from "../api/session";
import type { Integration, Me } from "../api/types";
import { useAuth } from "../App";
import { Badge, Button, Card, ErrorState, Field, Input, KeyValue, Loading, Notice, PageHeader, Select, StatusBadge, Table, Tabs, Td, TextField, Th } from "../components/ui";
import { useAction, useApi, withStepUp } from "../hooks/useApi";
import { fmtAgo, fmtTime } from "../lib/format";
import type { ApiError } from "../api/client";

type SettingsT = {
  preferences: { home_timezone: string; home_currency: string; default_venue: string };
  trading: { mode: string };
  limits: { max_order_notional_home: number; max_position_pct: number; max_orders_per_day: number; price_collar_pct: number; block_market_orders_outside_session: boolean; allowlist: Record<string, string[]> };
  retention: Record<string, number>;
  live_gate: { env_flag: boolean; authorized: boolean; requirements: string[]; status: string };
  modes_available: Record<string, boolean>;
};

export default function Settings() {
  const auth = useAuth();
  const role = isDemo ? "demo" : auth.data?.user?.role;
  const tabs = [{ value: "security", label: role === "collaborator" ? "My account" : "Security", content: <SecurityTab me={auth.data?.user ?? null} /> }];
  if (role !== "collaborator") {
    tabs.push(
      { value: "preferences", label: "Preferences", content: <PreferencesTab /> },
      { value: "trading", label: "Trading and limits", content: <TradingTab /> },
      { value: "integrations", label: "Integrations", content: <IntegrationsTab /> },
      { value: "data", label: "Data and privacy", content: <DataTab /> },
      { value: "system", label: "System", content: <SystemTab /> },
    );
  }
  return (
    <>
      <PageHeader title="Settings" help="security-and-privacy" />
      <Tabs tabs={tabs} />
    </>
  );
}

function SecurityTab({ me }: { me: Me | null }) {
  const sessions = useApi<{ id: string; current: boolean; created_at: string; last_seen_at: string; user_agent: string }[]>(["sessions"], isDemo ? null : "/auth/sessions");
  const [pw, setPw] = useState({ current_password: "", new_password: "" });
  const change = useAction<Body<"PasswordIn">>("POST", "/auth/password", { onSuccess: () => setPw({ current_password: "", new_password: "" }) });
  const qc = useQueryClient();
  const logoutAll = useAction("POST", "/auth/logout-all", { onSuccess: () => void clearClientSession(qc) });
  const [totp, setTotp] = useState<{ secret: string; otpauth_uri: string } | null>(null);
  const [code, setCode] = useState("");
  const [codes, setCodes] = useState<string[] | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  if (isDemo) return <Notice>The demo has no accounts. Security settings are available in your own workspace.</Notice>;
  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <Card title="Password">
        <form
          className="flex flex-col gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            change.mutate(pw);
          }}
        >
          <TextField label="Current password" type="password" autoComplete="current-password" value={pw.current_password} onChange={(e) => setPw({ ...pw, current_password: e.target.value })} />
          <TextField label="New password" type="password" autoComplete="new-password" hint="At least 12 characters. Other sessions are signed out." value={pw.new_password} onChange={(e) => setPw({ ...pw, new_password: e.target.value })} />
          {change.error && <p className="text-sm text-bad">{change.error.message}</p>}
          {change.isSuccess && <p className="text-sm text-good">Password changed. Other sessions were signed out.</p>}
          <Button type="submit" busy={change.isPending}>
            Change password
          </Button>
        </form>
      </Card>
      <Card title="Two-step sign-in (TOTP)" help="security-and-privacy">
        <p className="mb-3 text-sm">
          Status: <Badge tone={me?.totp_enabled ? "good" : "neutral"}>{me?.totp_enabled ? "enabled" : "off"}</Badge>
        </p>
        {!me?.totp_enabled && !totp && (
          <Button
            onClick={async () => {
              setError(null);
              try {
                setTotp(await withStepUp(() => post("/auth/totp/setup")));
              } catch (e) {
                setError(e as ApiError);
              }
            }}
          >
            Set up authenticator app
          </Button>
        )}
        {totp && !codes && (
          <div className="flex flex-col gap-2 text-sm">
            <p>Add this key to your authenticator app, then enter the 6-digit code.</p>
            <code className="break-all rounded bg-surface-2 p-2 text-xs">{totp.secret}</code>
            <Input aria-label="Authenticator code" inputMode="numeric" value={code} onChange={(e) => setCode(e.target.value)} />
            <Button
              variant="primary"
              onClick={async () => {
                setError(null);
                try {
                  const r = await post<{ recovery_codes: string[] }>("/auth/totp/enable", { code });
                  setCodes(r.recovery_codes);
                } catch (e) {
                  setError(e as ApiError);
                }
              }}
            >
              Verify and enable
            </Button>
          </div>
        )}
        {codes && (
          <Notice tone="accent" title="Recovery codes (shown once)">
            <ul className="num grid grid-cols-2 gap-1 font-mono text-xs">
              {codes.map((c) => (
                <li key={c}>{c}</li>
              ))}
            </ul>
            <p className="mt-1 text-xs">Store them offline. Each works once.</p>
          </Notice>
        )}
        {me?.totp_enabled && (
          <div className="flex gap-2">
            <Button
              onClick={async () => {
                try {
                  setCodes((await withStepUp(() => post<{ recovery_codes: string[] }>("/auth/recovery-codes"))).recovery_codes);
                } catch (e) {
                  setError(e as ApiError);
                }
              }}
            >
              New recovery codes
            </Button>
            <Button
              variant="danger"
              onClick={async () => {
                try {
                  await withStepUp(() => post("/auth/totp/disable"));
                  window.location.reload();
                } catch (e) {
                  setError(e as ApiError);
                }
              }}
            >
              Turn off
            </Button>
          </div>
        )}
        <ErrorState error={error} />
      </Card>
      <Card title="Active sessions" actions={<Button size="sm" variant="danger" onClick={() => logoutAll.mutate(undefined)}>Sign out everywhere</Button>}>
        {sessions.isLoading && <Loading />}
        <ul className="flex flex-col gap-1.5 text-sm">
          {(sessions.data ?? []).map((s) => (
            <li key={s.id} className="flex justify-between gap-2">
              <span className="truncate">
                {s.user_agent?.slice(0, 60) || "Unknown device"} {s.current && <Badge tone="good">this session</Badge>}
              </span>
              <span className="shrink-0 text-xs text-muted">active {fmtAgo(s.last_seen_at)}</span>
            </li>
          ))}
        </ul>
        <p className="mt-2 text-xs text-muted">Sessions end after 30 minutes idle or 12 hours in total.</p>
      </Card>
    </div>
  );
}

function PreferencesTab() {
  const q = useApi<SettingsT>(["settings"], "/settings");
  const [prefs, setPrefs] = useState<Body<"PrefsIn"> | null>(null);
  const save = useAction<Body<"PrefsIn">>("PUT", "/settings/preferences", { invalidate: [["settings"], ["venue-state"], ["portfolio"]] });
  if (!q.data) return <Loading />;
  const p = prefs ?? (q.data.preferences as Body<"PrefsIn">);
  return (
    <Card title="Home location and currency">
      <form
        className="grid grid-cols-1 max-w-lg gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate(p);
        }}
      >
        <TextField label="Home timezone (IANA)" value={p.home_timezone} onChange={(e) => setPrefs({ ...p, home_timezone: e.target.value })} hint="e.g. Asia/Jerusalem, Europe/London" disabled={isDemo} />
        <Field label="Home currency" htmlFor="hc">
          <Select id="hc" value={p.home_currency} disabled={isDemo} onChange={(e) => setPrefs({ ...p, home_currency: e.target.value as Body<"PrefsIn">["home_currency"] })}>
            {["ILS", "USD", "EUR", "GBP", "JPY"].map((c) => (
              <option key={c}>{c}</option>
            ))}
          </Select>
        </Field>
        {save.error && <p className="text-sm text-bad">{save.error.message}</p>}
        {!isDemo && (
          <Button type="submit" variant="primary" busy={save.isPending}>
            Save
          </Button>
        )}
      </form>
    </Card>
  );
}

function TradingTab() {
  const q = useApi<SettingsT>(["settings"], "/settings");
  const [limits, setLimits] = useState<SettingsT["limits"] | null>(null);
  const saveLimits = useAction<Body<"LimitsIn">>("PUT", "/settings/limits", { invalidate: [["settings"]], stepUp: true });
  const setMode = useAction<Body<"ModeIn">>("PUT", "/settings/trading-mode", { invalidate: [["settings"], ["broker"]], stepUp: true });
  if (!q.data) return <Loading />;
  const l = limits ?? q.data.limits;
  const num = (k: keyof SettingsT["limits"]) => (e: { target: { value: string } }) => setLimits({ ...l, [k]: Number(e.target.value) });
  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <Card title="Trading mode" help="modes">
        <ul className="flex flex-col gap-2 text-sm">
          {(["mock", "paper", "live"] as const).map((m) => (
            <li key={m} className="flex items-center justify-between gap-2 rounded border border-line p-2">
              <span>
                <strong>{m.toUpperCase()}</strong>
                <span className="block text-xs text-muted">
                  {m === "mock" ? "Simulated broker and synthetic data (default)." : m === "paper" ? "IBKR Paper account through IB Gateway — requires your own account and configuration." : q.data!.live_gate.status}
                </span>
              </span>
              {q.data!.trading.mode === m ? (
                <Badge tone="good">current</Badge>
              ) : (
                <Button size="sm" disabled={isDemo || !q.data!.modes_available[m]} onClick={() => setMode.mutate({ mode: m })}>
                  {q.data!.modes_available[m] ? "Switch" : "Unavailable"}
                </Button>
              )}
            </li>
          ))}
        </ul>
        {setMode.error && <p className="mt-2 text-sm text-bad">{setMode.error.message}</p>}
        <p className="mt-3 text-xs font-medium">Live activation would require:</p>
        <ul className="list-disc pl-5 text-xs text-muted">
          {q.data.live_gate.requirements.map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
      </Card>
      <Card title="Order limits (enforced by the backend)" help="approvals-and-stop">
        <form
          className="grid grid-cols-1 gap-3 sm:grid-cols-2"
          onSubmit={(e) => {
            e.preventDefault();
            saveLimits.mutate(l);
          }}
        >
          <TextField label="Max order value (home ccy)" type="number" value={l.max_order_notional_home} onChange={num("max_order_notional_home")} disabled={isDemo} />
          <TextField label="Max position (% of portfolio)" type="number" value={l.max_position_pct} onChange={num("max_position_pct")} disabled={isDemo} />
          <TextField label="Max orders per day" type="number" value={l.max_orders_per_day} onChange={num("max_orders_per_day")} disabled={isDemo} />
          <TextField label="Price collar (%)" type="number" value={l.price_collar_pct} onChange={num("price_collar_pct")} disabled={isDemo} />
          <label className="flex items-center gap-2 text-sm sm:col-span-2">
            <input type="checkbox" disabled={isDemo} checked={l.block_market_orders_outside_session} onChange={(e) => setLimits({ ...l, block_market_orders_outside_session: e.target.checked })} /> Block market orders while the venue is closed
          </label>
          {saveLimits.error && <p className="text-sm text-bad sm:col-span-2">{saveLimits.error.message}</p>}
          {!isDemo && (
            <div className="sm:col-span-2">
              <Button type="submit" variant="primary" busy={saveLimits.isPending}>
                Save limits
              </Button>
            </div>
          )}
        </form>
      </Card>
    </div>
  );
}

function IntegrationsTab() {
  const q = useApi<Integration[]>(["integrations"], "/settings/integrations");
  return (
    <Card title="Integrations and their verification status" help="integrations-status">
      <p className="mb-3 text-xs text-muted">
        Four statuses only: implemented and verified locally · implemented but externally unverified · verified against a real configured provider · not implemented or blocked. Mock success never counts as real-provider verification.
      </p>
      {q.isLoading && <Loading />}
      <Table caption="Integrations">
        <thead>
          <tr>
            <Th>Integration</Th>
            <Th>Status</Th>
            <Th>Detail</Th>
          </tr>
        </thead>
        <tbody>
          {(q.data ?? []).map((i) => (
            <tr key={i.key}>
              <Td>{i.name}</Td>
              <Td>
                <Badge tone={i.status.startsWith("Implemented and verified") ? "good" : i.status.startsWith("Verified against") ? "good" : i.status.startsWith("Implemented but") ? "warn" : "neutral"}>{i.status}</Badge>
              </Td>
              <Td className="text-xs text-muted">{i.detail}</Td>
            </tr>
          ))}
        </tbody>
      </Table>
    </Card>
  );
}

function DataTab() {
  const q = useApi<SettingsT>(["settings"], "/settings");
  const exports = useApi<{ id: string; created_at: string; size_bytes: number; documents: number }[]>(["exports"], "/settings/exports");
  const create = useAction("POST", "/settings/exports", { invalidate: [["exports"]] });
  const [ret, setRet] = useState<Body<"RetentionIn"> | null>(null);
  const saveRet = useAction<Body<"RetentionIn">>("PUT", "/settings/retention", { invalidate: [["settings"]] });
  const [phrase, setPhrase] = useState("");
  const [error, setError] = useState<ApiError | null>(null);
  if (!q.data) return <Loading />;
  const r = ret ?? (q.data.retention as Body<"RetentionIn">);
  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <Card title="Export your data" help="security-and-privacy">
        <p className="mb-3 text-sm text-muted">A ZIP with JSON for every table and your original documents. Secrets are excluded.</p>
        {!isDemo && (
          <Button busy={create.isPending} onClick={() => create.mutate(undefined)}>
            Create export
          </Button>
        )}
        <ul className="mt-3 flex flex-col gap-1 text-sm">
          {(exports.data ?? []).map((e) => (
            <li key={e.id} className="flex justify-between">
              <span>
                {fmtTime(e.created_at)} · {(e.size_bytes / 1e6).toFixed(2)} MB
              </span>
              {!isDemo && (
                <a className="text-accent hover:underline" href={`${apiBase}/settings/exports/${e.id}/download`}>
                  Download
                </a>
              )}
            </li>
          ))}
        </ul>
      </Card>
      <Card title="Retention">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {Object.entries(r).map(([k, v]) => (
            <TextField key={k} label={k.replace(/_/g, " ")} type="number" value={v} disabled={isDemo} onChange={(e) => setRet({ ...r, [k]: Number(e.target.value) })} />
          ))}
        </div>
        {!isDemo && (
          <Button className="mt-3" busy={saveRet.isPending} onClick={() => saveRet.mutate(r)}>
            Save retention
          </Button>
        )}
        <p className="mt-2 text-xs text-muted">A nightly job purges data older than these limits. Backups rotate separately (see Help → Operations).</p>
      </Card>
      {!isDemo && (
        <Card title="Delete all personal data">
          <Notice tone="bad">Deletes decisions, documents, orders, meetings, collaborators and your account. Existing backups keep data until they rotate out; the erasure ledger prevents restored backups from bringing it back.</Notice>
          <div className="mt-3 flex flex-col gap-2">
            <TextField label="Type DELETE ALL MY DATA to confirm" value={phrase} onChange={(e) => setPhrase(e.target.value)} />
            <ErrorState error={error} />
            <Button
              variant="danger"
              disabled={phrase !== "DELETE ALL MY DATA"}
              onClick={async () => {
                try {
                  await withStepUp(() => post("/settings/delete-all", { confirm_phrase: phrase } satisfies Body<"DeleteAllIn">));
                  window.location.href = "/";
                } catch (e) {
                  setError(e as ApiError);
                }
              }}
            >
              Delete everything
            </Button>
          </div>
        </Card>
      )}
    </div>
  );
}

type Summary = {
  requests_last_hour: number; error_rate_pct: number; latency_ms: { p50: number; p95: number }; queue: Record<string, number>; failed_jobs_24h: number;
  worker_heartbeat_seconds: number | null; runs_7d: { mode: string; status: string; count: number }[]; avg_run_seconds: Record<string, number>;
  agent_usage_7d: { output_kind: string; model: string | null; steps: number; tokens_in: number; tokens_out: number; avg_step_ms: number; tool_calls: number }[];
  orders_by_status: Record<string, number>; reconciliation_backlog: number; backup_age_hours: number | null; data_volume: { used_gb: number; free_gb: number } | null;
  slowest_routes: { route: string; count: number; p95_ms: number }[];
};
type AuditRow = { id: number; at: string; actor_role: string | null; action: string; object_type: string | null; object_id: string | null; correlation_id: string | null };

function SystemTab() {
  const s = useApi<Summary>(["ops"], "/ops/summary", { refetchInterval: 15_000 });
  const alerts = useApi<{ id: string; severity: string; message: string; help_slug: string; first_seen: string; count: number }[]>(["alerts"], "/ops/alerts");
  const sys = useApi<{ app_version: string; calendar_library: { version: string; note: string }; packages: Record<string, string>; model: { name: string }; embeddings: { enabled: boolean } }>(["system"], "/ops/system");
  const [filter, setFilter] = useState("");
  const audit = useApi<AuditRow[]>(["audit", filter], `/audit?limit=100${filter ? `&action=${encodeURIComponent(filter)}` : ""}`);
  return (
    <div className="flex flex-col gap-4">
      <Card title="Operations dashboard" help="operations-and-alerts">
        {s.isLoading && <Loading />}
        <ErrorState error={s.error} />
        {s.data && (
          <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
            <KeyValue
              items={[
                ["Requests (1 h)", s.data.requests_last_hour],
                ["Error rate", `${s.data.error_rate_pct}%`],
                ["Latency p50 / p95", `${s.data.latency_ms.p50} / ${s.data.latency_ms.p95} ms`],
                ["Worker heartbeat", s.data.worker_heartbeat_seconds === null ? <Badge tone="bad">not seen</Badge> : `${s.data.worker_heartbeat_seconds} s ago`],
                ["Backup age", s.data.backup_age_hours === null ? <Badge tone="warn">no backup recorded</Badge> : `${s.data.backup_age_hours} h`],
                ["Data volume", s.data.data_volume ? `${s.data.data_volume.used_gb} GB used · ${s.data.data_volume.free_gb} GB free` : "—"],
              ]}
            />
            <KeyValue
              items={[
                ["Job queue", Object.entries(s.data.queue).map(([k, v]) => `${k} ${v}`).join(" · ") || "empty"],
                ["Failed jobs (24 h)", s.data.failed_jobs_24h],
                ["Runs (7 d)", s.data.runs_7d.map((r) => `${r.mode}/${r.status} ${r.count}`).join(" · ") || "none"],
                ["Avg run time", Object.entries(s.data.avg_run_seconds).map(([k, v]) => `${k} ${v}s`).join(" · ") || "—"],
                ["Orders", Object.entries(s.data.orders_by_status).map(([k, v]) => `${k} ${v}`).join(" · ") || "none"],
                ["Reconciliation backlog", s.data.reconciliation_backlog],
              ]}
            />
            <div>
              <p className="mb-1 text-xs font-medium text-muted">Agent usage (7 d)</p>
              <ul className="text-xs">
                {s.data.agent_usage_7d.map((u, i) => (
                  <li key={i}>
                    {u.output_kind ?? "?"}
                    {u.model ? ` (${u.model})` : ""}: {u.steps} steps · {u.tool_calls} tool calls · avg {u.avg_step_ms} ms{u.tokens_in ? ` · ${u.tokens_in}/${u.tokens_out} tokens` : ""}
                  </li>
                ))}
              </ul>
              <p className="mb-1 mt-3 text-xs font-medium text-muted">Slowest routes (p95)</p>
              <ul className="text-xs">
                {s.data.slowest_routes.map((r) => (
                  <li key={r.route}>
                    {r.route}: {r.p95_ms} ms ({r.count})
                  </li>
                ))}
              </ul>
            </div>
          </div>
        )}
      </Card>
      <Card title="Alerts" help="operations-and-alerts">
        <ul className="flex flex-col gap-1.5 text-sm">
          {(alerts.data ?? []).map((a) => (
            <li key={a.id} className="flex items-center justify-between gap-2">
              <span>
                <StatusBadge status={a.severity === "critical" ? "failed" : "stale"} label={a.severity} /> {a.message} <span className="text-xs text-muted">×{a.count}</span>
              </span>
              <Link className="text-xs text-accent hover:underline" to={`/help/${a.help_slug}`}>
                How to fix
              </Link>
            </li>
          ))}
          {alerts.data?.length === 0 && <li className="text-muted">No open alerts.</li>}
        </ul>
      </Card>
      <Card title="Audit trail" actions={<Input aria-label="Filter actions" placeholder="Filter, e.g. order." className="w-48" value={filter} onChange={(e) => setFilter(e.target.value)} />}>
        <Table caption="Audit events">
          <thead>
            <tr>
              <Th>Time</Th>
              <Th>Actor</Th>
              <Th>Action</Th>
              <Th>Object</Th>
              <Th>Correlation</Th>
            </tr>
          </thead>
          <tbody>
            {(audit.data ?? []).map((e) => (
              <tr key={e.id}>
                <Td>{fmtTime(e.at, undefined, { second: "2-digit" })}</Td>
                <Td>{e.actor_role ?? "system"}</Td>
                <Td>
                  <code className="text-xs">{e.action}</code>
                </Td>
                <Td className="text-xs">
                  {e.object_type} {e.object_id?.slice(0, 8)}
                </Td>
                <Td className="text-xs text-muted">{e.correlation_id}</Td>
              </tr>
            ))}
          </tbody>
        </Table>
      </Card>
      {sys.data && (
        <Card title="System">
          <KeyValue
            items={[
              ["App version", sys.data.app_version],
              ["Exchange calendars", `${sys.data.calendar_library.version} — ${sys.data.calendar_library.note}`],
              ["Packages", Object.entries(sys.data.packages).map(([k, v]) => `${k} ${v}`).join(" · ")],
              ["Model", sys.data.model.name],
              ["Embeddings", sys.data.embeddings.enabled ? "enabled" : "disabled (keyword search)"],
            ]}
          />
        </Card>
      )}
      <Card title="Governance" help="governance">
        <ul className="list-disc pl-5 text-sm">
          <li>Only the owner can approve, submit, share, change limits, erase data or (in future) activate Live.</li>
          <li>Agents read and compute only; their proposals are inert until you act.</li>
          <li>Prompts are versioned files; model name and digest are recorded per step.</li>
          <li>Incident runbook: stop → assess → reconcile → document → lessons.</li>
        </ul>
      </Card>
    </div>
  );
}

