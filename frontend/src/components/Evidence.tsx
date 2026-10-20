import { useState } from "react";
import type { EvidenceItem, Snapshot } from "../api/types";
import { fmtMoney, fmtPct, fmtTime } from "../lib/format";
import { Badge, Card, Notice, OutputBadge, Table, Td, Th } from "./ui";

function byKind(items: EvidenceItem[], kind: string) {
  return items.filter((i) => i.kind === kind);
}

function Redacted({ item }: { item: EvidenceItem }) {
  return (
    <div className="rounded border border-dashed border-bad/50 px-3 py-2 text-sm text-muted">
      Erased evidence item ({item.redaction_reason?.replace("_", " ")}) on {fmtTime(item.redacted_at)}. Its content and salt were removed; the remaining items still verify.
    </div>
  );
}

export function ChecklistView({ checks }: { checks: { key: string; name: string; passed: boolean; detail: string; heuristic?: boolean }[] }) {
  const passed = checks.filter((c) => c.passed).length;
  return (
    <div>
      <p className="mb-2 text-sm">
        <span className="num text-lg font-semibold">
          {passed} of {checks.length}
        </span>{" "}
        checks passed
      </p>
      <p className="mb-3 text-xs text-muted">Passing checks means the process was complete, not that the idea is good.</p>
      <ul className="flex flex-col gap-1.5">
        {checks.map((c) => (
          <li key={c.key} className="flex items-start gap-2 text-sm">
            <span aria-hidden className={c.passed ? "text-good" : "text-bad"}>
              {c.passed ? "✓" : "✗"}
            </span>
            <span className="min-w-0">
              <span className="sr-only">{c.passed ? "Passed: " : "Failed: "}</span>
              {c.name} {c.heuristic && <Badge title="Heuristic: does not prove that a source supports a claim">heuristic</Badge>}
              <span className="block text-xs text-muted">{c.detail}</span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function EvidenceView({ snapshot, compact }: { snapshot: Snapshot; compact?: boolean }) {
  const items = snapshot.items;
  const [showHashes, setShowHashes] = useState(false);
  const get = (k: string) => byKind(items, k)[0];
  const sources = items.filter((i) => i.kind.startsWith("source_"));
  const passages = sources.filter((s) => s.kind === "source_passage");
  const data = sources.filter((s) => s.kind !== "source_passage");
  const checks = get("checks");
  const summary = get("research_summary");
  const analysis = get("analysis_notes");
  const counter = get("counterarguments");
  const findings = get("findings");
  const proposals = get("proposed_actions");
  const assumptions = get("assumptions");
  const context = get("portfolio_context");

  return (
    <div className="flex flex-col gap-4">
      {snapshot.banner && (
        <Notice tone="warn" title="Evidence incomplete">
          {snapshot.banner}
        </Notice>
      )}
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
        <Badge tone={snapshot.verification.ok ? "good" : "bad"}>{snapshot.verification.ok ? "Hashes verified" : "Verification failed"}</Badge>
        <span>
          Frozen {fmtTime(snapshot.created_at)} · {snapshot.items.length} items · {snapshot.verification.items_verified} verified
          {snapshot.verification.items_redacted ? ` · ${snapshot.verification.items_redacted} erased` : ""}
        </span>
        <button className="text-accent hover:underline" onClick={() => setShowHashes(!showHashes)}>
          {showHashes ? "Hide hashes" : "Show hashes"}
        </button>
      </div>
      {showHashes && (
        <pre tabIndex={0} className="overflow-x-auto rounded bg-surface-2 p-2 text-[11px]">
          snapshot {snapshot.snapshot_hash}
          {"\n"}
          {items.map((i) => `${String(i.ordinal).padStart(2, "0")} ${i.item_hash}  ${i.kind}`).join("\n")}
        </pre>
      )}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {checks && !checks.redacted_at && (
          <Card title="Evidence checklist" help="decision-checklist" actions={<OutputBadge label="computed" />}>
            <ChecklistView checks={checks.content?.checks ?? []} />
          </Card>
        )}
        {summary && (
          <Card title="Research summary" actions={<OutputBadge label={summary.output_label} detail={summary.provenance?.model?.model} />}>
            {summary.redacted_at ? <Redacted item={summary} /> : <p className="text-sm">{summary.content?.text}</p>}
          </Card>
        )}
      </div>
      <Card title={`Library passages (${passages.length})`} help="knowledge-library" actions={<Badge>Quoted evidence</Badge>}>
        {passages.length === 0 && <p className="text-sm text-muted">No library passages were cited.</p>}
        <ul className="flex flex-col gap-3">
          {passages.map((p) =>
            p.redacted_at ? (
              <li key={p.id}>
                <Redacted item={p} />
              </li>
            ) : (
              <li key={p.id} className="border-l-2 border-accent/50 pl-3">
                <p className="text-xs text-muted">
                  {p.title} · {p.provenance?.location} · retrieved {fmtTime(p.provenance?.retrieved_at)}
                  {p.source_removed_at && <Badge tone="warn" className="ml-2">Source removed from Library on {fmtTime(p.source_removed_at)}</Badge>}
                  {p.content?.selected_by_model && <Badge tone="model" className="ml-2">selected by model</Badge>}
                </p>
                <blockquote className="mt-1 text-sm">“{compact ? String(p.content?.quote ?? "").slice(0, 400) : p.content?.quote}”</blockquote>
                <p className="mt-0.5 text-[11px] text-muted">Untrusted document text, shown as data.</p>
              </li>
            ),
          )}
        </ul>
      </Card>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card title="Market and calendar data" actions={<OutputBadge label="computed" />}>
          <ul className="flex flex-col gap-2 text-sm">
            {data.map((s) => (
              <li key={s.id} className="flex flex-col">
                <span className="flex flex-wrap items-center gap-2">
                  {s.title}
                  {s.provenance?.freshness && <Badge tone={s.provenance.freshness === "stale" ? "bad" : "simulated"}>{s.provenance.freshness}</Badge>}
                </span>
                <span className="text-xs text-muted">
                  {s.content?.withheld
                    ? s.content.reason
                    : s.kind === "source_quote"
                      ? `${s.content?.price} ${s.content?.currency} (${fmtPct(s.content?.change_pct)}) · ${s.content?.label} · as of ${fmtTime(s.provenance?.as_of)}`
                      : s.kind === "source_calendar"
                        ? `${s.content?.state}${s.content?.reason ? ` — ${s.content.reason}` : ""}`
                        : ""}
                </span>
              </li>
            ))}
          </ul>
        </Card>
        {context && (
          <Card title="Portfolio context" actions={<OutputBadge label="computed" />}>
            {context.content?.withheld ? (
              <p className="text-sm text-muted">{context.content.reason}</p>
            ) : (
              <div className="text-sm">
                <p>
                  Total {fmtMoney(context.content?.total_home, context.content?.home_currency)} ({context.provenance?.label})
                </p>
                <ul className="mt-1 text-xs text-muted">
                  {(context.content?.instrument_weights ?? []).map((w: { symbol: string; weight_pct: number }) => (
                    <li key={w.symbol}>
                      {w.symbol}: {w.weight_pct}% of portfolio
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </Card>
        )}
      </div>
      {analysis && (
        <Card title="Portfolio and market analysis" actions={<OutputBadge label={analysis.output_label} detail={analysis.provenance?.model?.model} />}>
          {analysis.redacted_at ? <Redacted item={analysis} /> : (
            <ul className="list-disc pl-5 text-sm">
              {(analysis.content?.notes ?? []).map((n: string, i: number) => (
                <li key={i}>{n}</li>
              ))}
            </ul>
          )}
        </Card>
      )}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {counter && (
          <Card title="Counterarguments" actions={<OutputBadge label={counter.output_label} />}>
            {counter.redacted_at ? <Redacted item={counter} /> : (
              <ul className="list-disc pl-5 text-sm">
                {(counter.content?.items ?? []).map((n: string, i: number) => (
                  <li key={i}>{n}</li>
                ))}
              </ul>
            )}
          </Card>
        )}
        {findings && (
          <Card title="Critic findings and unresolved issues" actions={<OutputBadge label={findings.output_label} />}>
            <ul className="flex flex-col gap-1.5 text-sm">
              {(findings.content?.findings ?? []).map((f: { severity: string; title: string; detail: string }, i: number) => (
                <li key={i}>
                  <Badge tone={f.severity === "blocking" ? "bad" : f.severity === "warning" ? "warn" : "neutral"}>{f.severity}</Badge> {f.title}
                  <span className="block text-xs text-muted">{f.detail}</span>
                </li>
              ))}
              {(findings.content?.findings ?? []).length === 0 && <li className="text-muted">No findings.</li>}
            </ul>
          </Card>
        )}
      </div>
      {assumptions && (
        <Card title="Assumptions (for later review)" actions={<OutputBadge label="computed" />}>
          <ul className="flex flex-col gap-1 text-sm">
            {(assumptions.content?.assumptions ?? []).map((a: { code: string; text: string; expected?: string }) => (
              <li key={a.code}>
                <span className="font-mono text-xs text-accent">{a.code}</span> {a.text} {a.expected && <span className="text-xs text-muted">(expected: {a.expected})</span>}
              </li>
            ))}
          </ul>
        </Card>
      )}
      {proposals && (
        <Card title="Suggestions (not executed)" help="agents-and-labels">
          <p className="mb-2 text-xs text-muted">Agents may propose; only you act, through the normal screens with full checks and approvals.</p>
          <ul className="flex flex-col gap-2 text-sm">
            {(proposals.content?.proposals ?? []).map((p: { kind: string; rationale: string; label: string; payload: Record<string, unknown> }, i: number) => (
              <li key={i} className="flex flex-col">
                <span className="flex items-center gap-2">
                  <Badge>{p.kind.replace(/_/g, " ")}</Badge>
                  <OutputBadge label={p.label as never} />
                  <span className="text-xs text-muted">{JSON.stringify(p.payload)}</span>
                </span>
                <span className="text-xs text-muted">{p.rationale}</span>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}

export function ScenarioTable({ table }: { table: { rows: { name: string; shock_pct: number; fx_pct: number; portfolio_change_home: number; portfolio_change_pct: number; portfolio_after_home: number }[]; home_currency: string; method: string; includes_proposed_trade: boolean } }) {
  return (
    <div>
      <Table caption="Scenario results">
        <thead>
          <tr>
            <Th>Scenario</Th>
            <Th right>Instrument move</Th>
            <Th right>FX move</Th>
            <Th right>Portfolio change</Th>
            <Th right>Change %</Th>
            <Th right>Portfolio after</Th>
          </tr>
        </thead>
        <tbody>
          {table.rows.map((r) => (
            <tr key={r.name}>
              <Td>{r.name}</Td>
              <Td right>{fmtPct(r.shock_pct, 0)}</Td>
              <Td right>{fmtPct(r.fx_pct, 0)}</Td>
              <Td right className={r.portfolio_change_home < 0 ? "text-bad" : r.portfolio_change_home > 0 ? "text-good" : ""}>
                {fmtMoney(r.portfolio_change_home, table.home_currency)}
              </Td>
              <Td right>{fmtPct(r.portfolio_change_pct, 2)}</Td>
              <Td right>{fmtMoney(r.portfolio_after_home, table.home_currency)}</Td>
            </tr>
          ))}
        </tbody>
      </Table>
      <p className="mt-2 text-xs text-muted">
        {table.method}
        {table.includes_proposed_trade ? " Includes the simulated trade suggested by the question." : ""}
      </p>
    </div>
  );
}
