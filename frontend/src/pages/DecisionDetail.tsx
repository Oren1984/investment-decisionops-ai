import { useState } from "react";
import type { Body } from "../api/contract";
import { Link, useParams } from "react-router-dom";
import { isDemo } from "../api/client";
import type { DecisionDetail as Detail, Run, Snapshot } from "../api/types";
import { EvidenceView, ScenarioTable } from "../components/Evidence";
import { WorkflowBar } from "../components/layout/WorkflowBar";
import { Badge, Button, Card, EmptyState, ErrorState, Field, Input, Loading, Notice, PageHeader, Select, StatusBadge, Tabs, Textarea, TextField } from "../components/ui";
import { useAction, useApi } from "../hooks/useApi";
import { fmtTime } from "../lib/format";

export default function DecisionDetail() {
  const { id = "" } = useParams();
  const q = useApi<Detail>(["decision", id], `/decisions/${id}`, { refetchInterval: (query) => (query.state.data?.workflow.run && ["queued", "running"].includes(query.state.data.workflow.run.status) ? 2000 : 30_000) });
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorState error={q.error} retry={() => q.refetch()} />;
  const d = q.data!;
  const tabs = [
    { value: "evidence", label: "Evidence package", content: <EvidenceTab d={d} /> },
    { value: "scenarios", label: "Scenarios", content: <ScenariosTab d={d} /> },
    { value: "decide", label: d.status === "ready_for_decision" ? "Decide" : "Decision & versions", content: <DecideTab d={d} /> },
    { value: "runs", label: "Agent runs", content: <RunsTab d={d} /> },
    { value: "replay", label: "Replay", content: <ReplayTab d={d} /> },
    { value: "review", label: "Review & lessons", content: <ReviewTab d={d} /> },
    { value: "history", label: "History", content: <HistoryTab d={d} /> },
  ];
  return (
    <>
      <div className="-mx-3 -mt-4 mb-4 md:-mx-6">
        <WorkflowBar data={d.workflow} />
      </div>
      <PageHeader
        title={d.title}
        subtitle={<span>{d.question}</span>}
        help="decisions-and-replay"
        actions={
          <>
            <StatusBadge status={d.status} label={d.status_label} />
            {d.outcome && <Badge tone={d.outcome === "accept" ? "good" : d.outcome === "reject" ? "bad" : "neutral"}>Decision: {d.outcome} (v{d.current_version})</Badge>}
            {d.integrity_status === "redacted" && <Badge tone="warn">Evidence incomplete</Badge>}
          </>
        }
      />
      {d.status === "blocked" && d.blocked_reason && (
        <div className="mb-4">
          <Notice tone="bad" title="Blocked">
            {d.blocked_reason}
          </Notice>
        </div>
      )}
      <Tabs tabs={tabs} defaultValue={d.status === "ready_for_decision" ? "evidence" : "evidence"} />
    </>
  );
}

function useSnapshot(d: Detail) {
  return useApi<Snapshot>(["evidence", d.id, d.snapshot?.id], d.snapshot ? `/decisions/${d.id}/evidence` : null);
}

function EvidenceTab({ d }: { d: Detail }) {
  const ev = useSnapshot(d);
  if (!d.snapshot) {
    const active = d.workflow.run && ["queued", "running"].includes(d.workflow.run.status);
    return (
      <EmptyState title={active ? "Research in progress" : "No evidence package yet"}>
        {active ? `The ${d.workflow.run!.mode} run is at “${d.workflow.run!.current_step ?? "starting"}”. This page updates automatically.` : "Start a research run on the Agent runs tab."}
      </EmptyState>
    );
  }
  if (ev.isLoading) return <Loading />;
  if (ev.error) return <ErrorState error={ev.error} />;
  return <EvidenceView snapshot={ev.data!} />;
}

function ScenariosTab({ d }: { d: Detail }) {
  const ev = useSnapshot(d);
  const item = ev.data?.items.find((i) => i.kind === "scenarios");
  const comm = ev.data?.items.find((i) => i.kind === "scenario_commentary");
  if (!d.snapshot) return <EmptyState title="Scenarios appear once the evidence package is frozen." />;
  if (!item) return <Loading />;
  return (
    <Card title="Scenario results" help="decision-checklist" actions={<Badge tone="computed">Computed</Badge>}>
      <ScenarioTable table={item.content as never} />
      {comm?.content?.text && <p className="mt-3 text-sm">{comm.content.text} <Badge tone={comm.output_label === "model" ? "model" : "computed"}>{comm.output_label}</Badge></p>}
    </Card>
  );
}

function DecideTab({ d }: { d: Detail }) {
  const [outcome, setOutcome] = useState<Body<"DecideIn">["outcome"]>("accept");
  const [rationale, setRationale] = useState("");
  const [explanation, setExplanation] = useState("");
  const inv = [["decision", d.id], ["decisions"], ["workflow"]];
  const decide = useAction<Body<"DecideIn">>("POST", `/decisions/${d.id}/decide`, { invalidate: inv });
  const correct = useAction<Body<"CorrectionIn">>("POST", `/decisions/${d.id}/corrections`, { invalidate: inv });
  const dismiss = useAction<{ id: string }>("POST", (b) => `/proposals/${b.id}/dismiss`, { invalidate: inv });
  const canDecide = d.status === "ready_for_decision" && !isDemo;
  const canCorrect = ["decided", "execution_linked"].includes(d.status) && !isDemo;
  const orderIntent = d.proposals.find((p) => p.kind === "order_intent" && p.status === "open");
  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <Card title={canDecide ? "Record your decision" : "Decision versions"} help="decisions-and-replay">
        {canDecide && (
          <form
            className="flex flex-col gap-3"
            onSubmit={(e) => {
              e.preventDefault();
              decide.mutate({ outcome, rationale });
            }}
          >
            <p className="text-sm text-muted">
              Evidence package frozen with {d.snapshot?.checks_passed} of {d.snapshot?.checks_total} checks passed. Your decision is bound to this snapshot.
            </p>
            <Field label="Decision" htmlFor="outcome">
              <Select id="outcome" value={outcome} onChange={(e) => setOutcome(e.target.value as Body<"DecideIn">["outcome"])}>
                <option value="accept">Accept</option>
                <option value="reject">Reject</option>
                <option value="defer">Defer</option>
              </Select>
            </Field>
            <Field label="Rationale" htmlFor="rat" hint="Why, in your own words. This is what you will review later.">
              <Textarea id="rat" value={rationale} onChange={(e) => setRationale(e.target.value)} />
            </Field>
            {decide.error && <p className="text-sm text-bad">{decide.error.message}</p>}
            <Button type="submit" variant="primary" busy={decide.isPending} disabled={rationale.length < 10}>
              Record decision
            </Button>
          </form>
        )}
        <ul className="mt-2 flex flex-col gap-2 text-sm">
          {d.versions.map((v) => (
            <li key={v.version_no} className="rounded border border-line p-2">
              <p>
                <strong>v{v.version_no}</strong> · {v.kind} · <Badge>{v.outcome}</Badge> · {fmtTime(v.created_at)}
              </p>
              <p className="mt-1">{v.rationale}</p>
              {v.explanation && <p className="mt-1 text-xs text-muted">Correction: {v.explanation}</p>}
            </li>
          ))}
          {d.versions.length === 0 && !canDecide && <li className="text-muted">No decision recorded yet.</li>}
        </ul>
        {canCorrect && (
          <form
            className="mt-4 flex flex-col gap-2 border-t border-line pt-3"
            onSubmit={(e) => {
              e.preventDefault();
              correct.mutate({ outcome, rationale, explanation });
            }}
          >
            <p className="text-sm font-medium">Record a correction (creates a new version)</p>
            <Select aria-label="Corrected decision" value={outcome} onChange={(e) => setOutcome(e.target.value as Body<"DecideIn">["outcome"])}>
              <option value="accept">Accept</option>
              <option value="reject">Reject</option>
              <option value="defer">Defer</option>
            </Select>
            <Textarea aria-label="Corrected rationale" placeholder="Corrected rationale" value={rationale} onChange={(e) => setRationale(e.target.value)} />
            <Input aria-label="Explanation of the correction" placeholder="What changed and why" value={explanation} onChange={(e) => setExplanation(e.target.value)} />
            {correct.error && <p className="text-sm text-bad">{correct.error.message}</p>}
            <Button type="submit" busy={correct.isPending} disabled={rationale.length < 10 || explanation.length < 10}>
              Save correction
            </Button>
          </form>
        )}
      </Card>
      <div className="flex flex-col gap-4">
        <Card title="Suggestions (not executed)" help="agents-and-labels">
          <ul className="flex flex-col gap-2 text-sm">
            {d.proposals.map((p) => (
              <li key={p.id} className="flex items-start justify-between gap-2">
                <span>
                  <Badge>{p.kind.replace(/_/g, " ")}</Badge> <Badge tone={p.output_label === "model" ? "model" : "computed"}>{p.output_label}</Badge>
                  <span className="mt-0.5 block text-xs text-muted">{p.rationale}</span>
                </span>
                {p.status === "open" && !isDemo ? (
                  <Button size="sm" variant="ghost" onClick={() => dismiss.mutate({ id: p.id })}>
                    Dismiss
                  </Button>
                ) : (
                  <Badge>{p.status}</Badge>
                )}
              </li>
            ))}
            {d.proposals.length === 0 && <li className="text-muted">No suggestions.</li>}
          </ul>
        </Card>
        <Card title="Linked orders" help="approvals-and-stop">
          <ul className="flex flex-col gap-1 text-sm">
            {d.orders.map((o) => (
              <li key={o.id} className="flex justify-between">
                <Link to={`/orders/${o.id}`} className="hover:underline">
                  {o.side} {o.quantity} ({o.mode})
                </Link>
                <StatusBadge status={o.status} />
              </li>
            ))}
            {d.orders.length === 0 && <li className="text-muted">No orders linked.</li>}
          </ul>
          {["decided", "execution_linked"].includes(d.status) && d.outcome === "accept" && !isDemo && (
            <Link
              to={`/orders?new=1&decision=${d.id}${orderIntent ? `&symbol=${String(orderIntent.payload.symbol)}&side=${String(orderIntent.payload.side)}` : ""}`}
              className="mt-3 inline-block"
            >
              <Button size="sm" variant="primary">
                Create order ticket
              </Button>
            </Link>
          )}
        </Card>
      </div>
    </div>
  );
}

function RunsTab({ d }: { d: Detail }) {
  const runs = useApi<Run[]>(["runs", d.id], `/decisions/${d.id}/runs`, { refetchInterval: 3000 });
  const agents = useApi<{ modes: { model: boolean }; model: { reason?: string; model: string; ready: boolean } }>(["agents"], "/agents/status");
  const inv = [["runs", d.id], ["decision", d.id], ["workflow"]];
  const start = useAction<Body<"RunIn">>("POST", `/decisions/${d.id}/runs`, { invalidate: inv });
  const cancel = useAction<{ id: string }>("POST", (b) => `/runs/${b.id}/cancel`, { invalidate: inv });
  const resume = useAction<{ id: string }>("POST", (b) => `/runs/${b.id}/resume`, { invalidate: inv });
  const runnable = ["draft", "blocked", "cancelled", "ready_for_decision"].includes(d.status);
  const err = start.error ?? cancel.error ?? resume.error;
  return (
    <Card
      title="Agent runs"
      help="agents-and-labels"
      actions={
        !isDemo && runnable && (
          <div className="flex gap-2">
            <Button size="sm" variant="primary" busy={start.isPending} onClick={() => start.mutate({ mode: "deterministic" })}>
              Run deterministic
            </Button>
            <Button size="sm" disabled={!agents.data?.modes.model} title={agents.data?.model.reason} onClick={() => start.mutate({ mode: "model" })}>
              Run with local model
            </Button>
          </div>
        )
      }
    >
      {!agents.data?.modes.model && <p className="mb-3 text-xs text-muted">Model mode unavailable: {agents.data?.model.reason ?? "checking…"}. <Link className="text-accent" to="/help/local-model">Set up a local model</Link></p>}
      {err && <p className="mb-2 text-sm text-bad">{err.message}</p>}
      {runs.isLoading && <Loading />}
      <ul className="flex flex-col gap-2">
        {(runs.data ?? []).map((r) => (
          <li key={r.id} className="flex flex-wrap items-center justify-between gap-2 rounded border border-line p-2 text-sm">
            <span className="flex items-center gap-2">
              <Badge tone={r.mode === "model" ? "model" : "computed"}>{r.mode}</Badge>
              <StatusBadge status={r.status} />
              <span className="text-xs text-muted">
                {fmtTime(r.created_at)}
                {r.current_step && ["running", "queued"].includes(r.status) ? ` · ${r.current_step}` : ""}
                {r.resume_count ? ` · resumed ${r.resume_count}×` : ""}
              </span>
              {r.error && <span className="text-xs text-bad">{r.error}</span>}
            </span>
            <span className="flex gap-2">
              {!isDemo && ["queued", "running"].includes(r.status) && (
                <Button size="sm" variant="danger" onClick={() => cancel.mutate({ id: r.id })} disabled={r.cancel_requested}>
                  {r.cancel_requested ? "Cancelling…" : "Cancel"}
                </Button>
              )}
              {!isDemo && ["interrupted", "failed", "cancelled"].includes(r.status) && runnable && (
                <Button size="sm" onClick={() => resume.mutate({ id: r.id })}>
                  Resume
                </Button>
              )}
              <Link to={`/decisions/${d.id}/runs/${r.id}`}>
                <Button size="sm" variant="ghost">
                  Open workspace →
                </Button>
              </Link>
            </span>
          </li>
        ))}
        {runs.data?.length === 0 && <li className="text-sm text-muted">No runs yet.</li>}
      </ul>
    </Card>
  );
}

function ReplayTab({ d }: { d: Detail }) {
  const [version, setVersion] = useState(d.current_version || 1);
  const q = useApi<Snapshot & { version: { version_no: number; outcome: string; rationale: string; created_at: string }; decision: { question: string } }>(
    ["replay", d.id, version], d.current_version ? `/decisions/${d.id}/replay?version=${version}` : null,
  );
  if (!d.current_version) return <EmptyState title="Replay becomes available once you record a decision." />;
  return (
    <div className="flex flex-col gap-4">
      <Notice>Replay shows exactly what was known when the decision was recorded. It reads only the frozen snapshot; later market data never changes it.</Notice>
      <div className="flex items-center gap-2">
        <label htmlFor="ver" className="text-sm text-muted">
          Version
        </label>
        <Select id="ver" className="w-auto" value={version} onChange={(e) => setVersion(Number(e.target.value))}>
          {d.versions.map((v) => (
            <option key={v.version_no} value={v.version_no}>
              v{v.version_no} · {v.kind} · {v.outcome}
            </option>
          ))}
        </Select>
      </div>
      {q.isLoading && <Loading />}
      {q.data && (
        <>
          <Card title={`Decision v${q.data.version.version_no}: ${q.data.version.outcome}`}>
            <p className="text-sm">{q.data.version.rationale}</p>
            <p className="mt-1 text-xs text-muted">Recorded {fmtTime(q.data.version.created_at)}</p>
          </Card>
          <EvidenceView snapshot={q.data} compact />
        </>
      )}
    </div>
  );
}

function ReviewTab({ d }: { d: Detail }) {
  const [rubric, setRubric] = useState<Record<string, number>>(Object.fromEntries(Object.keys(d.rubric).map((k) => [k, 1])));
  const [ret, setRet] = useState("");
  const [bench, setBench] = useState("");
  const [notes, setNotes] = useState("");
  const [lesson, setLesson] = useState("");
  const [tags, setTags] = useState("");
  const [obs, setObs] = useState<Record<string, { observation: string; held: string }>>({});
  const [close, setClose] = useState(false);
  const submit = useAction<Body<"ReviewIn">>("POST", `/decisions/${d.id}/reviews`, { invalidate: [["decision", d.id], ["insights"], ["lessons"]] });
  const reviewable = ["decided", "execution_linked", "under_review"].includes(d.status) && !isDemo;
  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <div className="flex flex-col gap-4">
        {d.reviews.map((r) => (
          <Card key={r.id} title={`Review ${fmtTime(r.created_at)}`}>
            <div className="flex flex-wrap gap-2 text-sm">
              <Badge tone={r.quadrant.process_good ? "good" : "warn"}>
                Process {r.process_score}/{r.process_max}
              </Badge>
              <Badge tone={r.quadrant.outcome_good === null ? "neutral" : r.quadrant.outcome_good ? "good" : "bad"}>
                Outcome {r.outcome_return_pct ?? "—"}% vs benchmark {r.benchmark_return_pct ?? "—"}%
              </Badge>
            </div>
            <ul className="mt-2 text-sm">
              {r.assumption_observations.map((o) => (
                <li key={o.assumption_code}>
                  <span className="font-mono text-xs text-accent">{o.assumption_code}</span> {o.observation} {o.held === true ? "✓ held" : o.held === false ? "✗ did not hold" : ""}
                </li>
              ))}
            </ul>
            {r.notes && <p className="mt-2 text-sm text-muted">{r.notes}</p>}
          </Card>
        ))}
        <Card title="Lessons">
          <ul className="list-disc pl-5 text-sm">
            {d.lessons.map((l) => (
              <li key={l.id}>
                {l.text} {l.tags.map((t) => <Badge key={t}>{t}</Badge>)}
              </li>
            ))}
            {d.lessons.length === 0 && <li className="list-none text-muted">No lessons yet.</li>}
          </ul>
        </Card>
      </div>
      {reviewable ? (
        <Card title="Review this decision" help="reviews-and-lessons">
          <form
            className="flex flex-col gap-3"
            onSubmit={(e) => {
              e.preventDefault();
              submit.mutate({
                process_rubric: rubric,
                outcome_return_pct: ret === "" ? null : Number(ret),
                benchmark_return_pct: bench === "" ? null : Number(bench),
                assumption_observations: d.assumptions.filter((a) => obs[a.code]?.observation).map((a) => ({ assumption_code: a.code, observation: obs[a.code].observation, held: obs[a.code].held === "" ? null : obs[a.code].held === "yes" })),
                notes: notes || null,
                lessons: lesson ? [{ text: lesson, tags: tags.split(",").map((t) => t.trim()).filter(Boolean) }] : [],
                close,
              });
            }}
          >
            <p className="text-sm font-medium">Assumptions vs. what happened</p>
            {d.assumptions.map((a) => (
              <div key={a.code} className="grid grid-cols-1 gap-1 sm:grid-cols-[minmax(0,1fr)_110px]">
                <Input aria-label={`Observation for ${a.code}`} placeholder={`${a.code}: ${a.text}`} value={obs[a.code]?.observation ?? ""} onChange={(e) => setObs({ ...obs, [a.code]: { held: obs[a.code]?.held ?? "", observation: e.target.value } })} />
                <Select aria-label={`Did ${a.code} hold?`} value={obs[a.code]?.held ?? ""} onChange={(e) => setObs({ ...obs, [a.code]: { observation: obs[a.code]?.observation ?? "", held: e.target.value } })}>
                  <option value="">Held?</option>
                  <option value="yes">Held</option>
                  <option value="no">Did not hold</option>
                </Select>
              </div>
            ))}
            <p className="mt-2 text-sm font-medium">Process quality (0–2 each)</p>
            {Object.entries(d.rubric).map(([k, label]) => (
              <div key={k} className="flex items-center justify-between gap-2 text-sm">
                <span>{label}</span>
                <Select aria-label={label} className="w-20" value={rubric[k]} onChange={(e) => setRubric({ ...rubric, [k]: Number(e.target.value) })}>
                  <option value={0}>0</option>
                  <option value={1}>1</option>
                  <option value={2}>2</option>
                </Select>
              </div>
            ))}
            <p className="mt-2 text-sm font-medium">Outcome (graded separately)</p>
            <div className="grid grid-cols-2 gap-2">
              <TextField label="Return %" type="number" step="any" value={ret} onChange={(e) => setRet(e.target.value)} />
              <TextField label="Benchmark %" type="number" step="any" value={bench} onChange={(e) => setBench(e.target.value)} />
            </div>
            <Field label="Notes" htmlFor="rn">
              <Textarea id="rn" value={notes} onChange={(e) => setNotes(e.target.value)} />
            </Field>
            <TextField label="Lesson" value={lesson} onChange={(e) => setLesson(e.target.value)} />
            <TextField label="Lesson tags (comma separated)" value={tags} onChange={(e) => setTags(e.target.value)} />
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={close} onChange={(e) => setClose(e.target.checked)} /> Close the decision after this review
            </label>
            {submit.error && <p className="text-sm text-bad">{submit.error.message}</p>}
            <Button type="submit" variant="primary" busy={submit.isPending}>
              Save review
            </Button>
          </form>
        </Card>
      ) : (
        <EmptyState title={d.status === "closed" ? "This decision is closed." : "Reviews become available after you decide."} />
      )}
    </div>
  );
}

function HistoryTab({ d }: { d: Detail }) {
  return (
    <Card title="Visible history" help="decisions-and-replay">
      <ol className="flex flex-col gap-2 border-l border-line pl-4 text-sm">
        {d.events.map((e, i) => (
          <li key={i}>
            <span className="text-xs text-muted">{fmtTime(e.at)}</span> <Badge tone={e.kind === "redaction" ? "bad" : e.kind === "blocked" ? "warn" : "neutral"}>{e.kind.replace(/_/g, " ")}</Badge>
            <p>{e.summary}</p>
          </li>
        ))}
      </ol>
    </Card>
  );
}
