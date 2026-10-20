import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { isDemo } from "../api/client";
import type { Run, RunStep } from "../api/types";
import { Badge, Button, Card, ErrorState, KeyValue, Loading, Notice, OutputBadge, PageHeader, StatusBadge } from "../components/ui";
import { useAction, useApi } from "../hooks/useApi";
import { fmtTime } from "../lib/format";

type Roles = { roles: { role: string; implementation?: string; model_mode?: string; tools: string[]; budget: string }[] };

export default function AgentWorkspace() {
  const { id = "", runId = "" } = useParams();
  const run = useApi<Run>(["run", runId], `/runs/${runId}`, { refetchInterval: (q) => (q.state.data && ["queued", "running"].includes(q.state.data.status) ? 1500 : false) });
  const team = useApi<Roles>(["agents"], "/agents/status");
  const inv = [["run", runId], ["decision", id], ["workflow"]];
  const cancel = useAction("POST", `/runs/${runId}/cancel`, { invalidate: inv });
  const resume = useAction("POST", `/runs/${runId}/resume`, { invalidate: inv });
  if (run.isLoading) return <Loading />;
  if (run.error) return <ErrorState error={run.error} />;
  const r = run.data!;
  const active = ["queued", "running"].includes(r.status);
  return (
    <>
      <PageHeader
        title="Agent workspace"
        subtitle={<Link to={`/decisions/${id}`} className="text-accent hover:underline">← Back to the decision</Link>}
        help="agents-and-labels"
        actions={
          <>
            <Badge tone={r.mode === "model" ? "model" : "computed"}>{r.mode} mode</Badge>
            <StatusBadge status={r.status} />
            {!isDemo && active && (
              <Button size="sm" variant="danger" onClick={() => cancel.mutate(undefined)} disabled={r.cancel_requested}>
                {r.cancel_requested ? "Cancelling…" : "Cancel run"}
              </Button>
            )}
            {!isDemo && ["interrupted", "failed", "cancelled"].includes(r.status) && (
              <Button size="sm" onClick={() => resume.mutate(undefined)} busy={resume.isPending}>
                Resume from last completed step
              </Button>
            )}
          </>
        }
      />
      {(cancel.error || resume.error) && <p className="mb-3 text-sm text-bad">{(cancel.error ?? resume.error)!.message}</p>}
      {r.error && (
        <div className="mb-4">
          <Notice tone={r.status === "blocked" ? "warn" : "bad"} title={`Run ${r.status}`}>
            {r.error}
          </Notice>
        </div>
      )}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <div className="flex flex-col gap-3 xl:col-span-2">
          <p className="text-xs text-muted">
            Orchestration: CrewAI Flow (deterministic routing, budgets, assembly). Steps write only their own outputs; a resumed run skips completed steps, so nothing is duplicated.
          </p>
          {(r.steps ?? []).map((s) => (
            <StepCard key={s.id} s={s} />
          ))}
          {active && (
            <div className="rounded border border-dashed border-line p-3 text-sm text-muted" role="status">
              Waiting for the next step… (updates automatically)
            </div>
          )}
        </div>
        <div className="flex flex-col gap-4">
          <Card title="Run details">
            <KeyValue
              items={[
                ["Started", fmtTime(r.started_at)],
                ["Finished", fmtTime(r.finished_at)],
                ["Deadline", fmtTime(r.deadline_at)],
                ["Model", r.model_name ? `${r.model_name} (${r.model_digest?.slice(0, 12)})` : "None (deterministic)"],
                ["Correlation ID", <code className="text-xs">{r.correlation_id ?? "—"}</code>],
                ["Resumed", `${r.resume_count}×`],
              ]}
            />
          </Card>
          <Card title="MCP tool calls">
            <ul className="text-sm">
              {Object.entries(r.tool_calls ?? {}).map(([tool, c]) => (
                <li key={tool} className="flex justify-between">
                  <code className="text-xs">{tool}</code>
                  <span className="num text-xs">
                    {c.ok} ok{c.failed ? <span className="text-bad"> · {c.failed} refused/failed</span> : null}
                  </span>
                </li>
              ))}
              {Object.keys(r.tool_calls ?? {}).length === 0 && <li className="text-muted">None yet.</li>}
            </ul>
            <p className="mt-2 text-[11px] text-muted">Tools are read/compute-only and authorized per call with a run capability token. There are no tools for orders, sharing, settings or deletion.</p>
          </Card>
          <Card title="Team and budgets">
            <ul className="flex flex-col gap-2 text-sm">
              {(team.data?.roles ?? []).map((x) => (
                <li key={x.role}>
                  <span className="font-medium">{x.role}</span> <span className="text-xs text-muted">· {x.budget}</span>
                  {x.tools.length > 0 && <span className="block text-xs text-muted">{x.tools.join(", ")}</span>}
                </li>
              ))}
            </ul>
          </Card>
        </div>
      </div>
    </>
  );
}

function StepCard({ s }: { s: RunStep }) {
  const [open, setOpen] = useState(false);
  return (
    <Card
      title={
        <span className="flex flex-wrap items-center gap-2">
          {s.label}
          {s.attempt > 1 && <Badge>attempt {s.attempt}</Badge>}
        </span>
      }
      actions={
        <>
          {s.output_kind && <OutputBadge label={s.output_kind} detail={s.model_name ? `${s.model_name} · ${s.prompt_version}` : undefined} />}
          <StatusBadge status={s.status} />
        </>
      }
    >
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
        <span>{fmtTime(s.started_at, undefined, { second: "2-digit" })}</span>
        {s.duration_ms !== null && <span>{(s.duration_ms / 1000).toFixed(1)} s</span>}
        <span>{s.tool_calls} tool call(s)</span>
        {s.tokens_in !== null && (
          <span>
            tokens {s.tokens_in}→{s.tokens_out}
          </span>
        )}
      </div>
      {s.notes.map((n, i) => (
        <p key={i} className="mt-2 text-xs text-warn">
          {n}
        </p>
      ))}
      {s.error && <p className="mt-2 text-sm text-bad">{s.error}</p>}
      {s.redacted && <p className="mt-2 text-sm text-muted">Output erased (a source document was fully erased).</p>}
      {s.output && !s.redacted && (
        <div className="mt-2">
          <button className="text-xs text-accent hover:underline" onClick={() => setOpen(!open)} aria-expanded={open}>
            {open ? "Hide output" : "Show structured output"}
          </button>
          {open && <pre className="mt-2 max-h-96 overflow-auto rounded bg-surface-2 p-2 text-[11px]">{JSON.stringify(s.output, null, 2)}</pre>}
        </div>
      )}
    </Card>
  );
}
