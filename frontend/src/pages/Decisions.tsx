import { useState } from "react";
import { Link } from "react-router-dom";
import { isDemo } from "../api/client";
import type { DecisionSummary } from "../api/types";
import { Badge, Button, Card, EmptyState, ErrorState, Input, Loading, PageHeader, StatusBadge, Table, Td, Th } from "../components/ui";
import { useApi } from "../hooks/useApi";
import { fmtTime } from "../lib/format";

type Insight = { cells: Record<string, { decision_id: string; title: string; process: string; return_pct: number | null; benchmark_pct: number | null }[]>; tags: { tag: string; count: number }[]; note: string };
type Lesson = { id: string; text: string; tags: string[]; decision_id: string; decision_title: string };

export default function Decisions() {
  const q = useApi<DecisionSummary[]>(["decisions"], "/decisions");
  const [filter, setFilter] = useState("");
  const rows = (q.data ?? []).filter((d) => !filter || d.status === filter);
  const statuses = [...new Set((q.data ?? []).map((d) => d.status))];
  return (
    <>
      <PageHeader
        title="Research and decisions"
        subtitle="Each question becomes a traceable decision record with a frozen evidence package."
        help="decisions-and-replay"
        actions={!isDemo && (
          <Link to="/decisions/new">
            <Button variant="primary">New question</Button>
          </Link>
        )}
      />
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <div className="xl:col-span-2">
          <Card title="Decision records" id="records" actions={
            <select aria-label="Filter by status" className="rounded border border-line bg-surface-2 px-1.5 py-0.5 text-xs" value={filter} onChange={(e) => setFilter(e.target.value)}>
              <option value="">All statuses</option>
              {statuses.map((s) => <option key={s} value={s}>{s.replace(/_/g, " ")}</option>)}
            </select>
          }>
            {q.isLoading && <Loading />}
            <ErrorState error={q.error} retry={() => q.refetch()} />
            {q.data && rows.length === 0 && <EmptyState title="No decisions yet" action={!isDemo && <Link className="text-sm text-accent" to="/decisions/new">Ask a question →</Link>} />}
            {rows.length > 0 && (
              <Table caption="Decisions">
                <thead>
                  <tr>
                    <Th>Title</Th>
                    <Th>Status</Th>
                    <Th>Checks</Th>
                    <Th>Outcome</Th>
                    <Th>Updated</Th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((d) => (
                    <tr key={d.id}>
                      <Td>
                        <Link to={`/decisions/${d.id}`} className="font-medium hover:underline">
                          {d.title}
                        </Link>
                        {d.integrity_status === "redacted" && <Badge tone="warn" className="ml-2">Evidence incomplete</Badge>}
                      </Td>
                      <Td>
                        <StatusBadge status={d.status} label={d.status_label} />
                      </Td>
                      <Td>{d.checks ? <span className="num">{d.checks.passed}/{d.checks.total}</span> : "—"}</Td>
                      <Td>{d.outcome ? <Badge tone={d.outcome === "accept" ? "good" : d.outcome === "reject" ? "bad" : "neutral"}>{d.outcome}</Badge> : "—"}</Td>
                      <Td>{fmtTime(d.updated_at)}</Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            )}
          </Card>
        </div>
        <div className="flex flex-col gap-4">
          <InsightsCard />
          <LessonsCard />
        </div>
      </div>
    </>
  );
}

const CELL_LABEL: Record<string, string> = {
  good_process_good_outcome: "Good process · good outcome",
  good_process_bad_outcome: "Good process · bad outcome",
  bad_process_good_outcome: "Weak process · good outcome",
  bad_process_bad_outcome: "Weak process · bad outcome",
};

function InsightsCard() {
  const q = useApi<Insight>(["insights"], "/decisions/insights");
  return (
    <Card title="Process vs. outcome" id="insights" help="reviews-and-lessons">
      {q.data && (
        <>
          <div className="grid grid-cols-2 gap-2">
            {Object.entries(CELL_LABEL).map(([k, label]) => (
              <div key={k} className="rounded border border-line p-2">
                <p className="text-[11px] text-muted">{label}</p>
                <p className="num text-lg font-semibold">{q.data!.cells[k]?.length ?? 0}</p>
                <ul className="text-xs">
                  {(q.data!.cells[k] ?? []).slice(0, 3).map((x) => (
                    <li key={x.decision_id} className="truncate">
                      <Link className="hover:underline" to={`/decisions/${x.decision_id}`}>
                        {x.title}
                      </Link>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
          <p className="mt-2 text-xs text-muted">{q.data.note}</p>
        </>
      )}
    </Card>
  );
}

function LessonsCard() {
  const [term, setTerm] = useState("");
  const q = useApi<Lesson[]>(["lessons", term], `/lessons${term ? `?q=${encodeURIComponent(term)}` : ""}`);
  return (
    <Card title="Lessons" id="lessons">
      <Input aria-label="Search lessons" placeholder="Search lessons" value={term} onChange={(e) => setTerm(e.target.value)} />
      <ul className="mt-3 flex flex-col gap-2 text-sm">
        {(q.data ?? []).map((l) => (
          <li key={l.id}>
            <p>{l.text}</p>
            <p className="text-xs text-muted">
              <Link to={`/decisions/${l.decision_id}`} className="hover:underline">
                {l.decision_title}
              </Link>{" "}
              {l.tags.map((t) => (
                <Badge key={t} className="ml-1">
                  {t}
                </Badge>
              ))}
            </p>
          </li>
        ))}
        {q.data?.length === 0 && <li className="text-muted">No lessons yet. They are captured in decision reviews.</li>}
      </ul>
    </Card>
  );
}
