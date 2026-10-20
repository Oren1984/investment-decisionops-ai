import { Link } from "react-router-dom";
import type { WorkflowBarData } from "../../api/types";
import { useApi } from "../../hooks/useApi";
import { Badge, cx } from "../ui";

/** Compact, persistent view of real workflow state: stage, completed stages, blockers and next action. */
export function WorkflowBar({ data: given }: { data?: WorkflowBarData }) {
  const q = useApi<WorkflowBarData | null>(["workflow"], given ? null : "/workflow/current", { refetchInterval: 10_000 });
  const data = given ?? q.data;
  if (!data) return null;
  const runActive = data.run && ["queued", "running"].includes(data.run.status);
  const current = data.stages.find((s) => s.state === "current");
  return (
    <div className="border-b border-line bg-surface/60 px-3 py-2 md:px-6" aria-label="Workflow status">
      <div className="mx-auto flex max-w-[1500px] flex-wrap items-center gap-x-4 gap-y-1.5 text-xs">
        <Link to={`/decisions/${data.decision_id}`} className="max-w-[240px] truncate font-medium hover:underline" title={data.title}>
          {data.title}
        </Link>
        <ol className="flex items-center gap-1 overflow-x-auto" aria-label="Stages" tabIndex={0}>
          {data.stages.map((s, i) => (
            <li key={s.key} className="flex items-center gap-1">
              {i > 0 && <span aria-hidden className={cx("h-px w-3", s.state === "todo" ? "bg-line" : "bg-accent")} />}
              <span
                title={s.label}
                aria-current={s.state === "current" ? "step" : undefined}
                className={cx(
                  "whitespace-nowrap rounded px-1.5 py-0.5",
                  s.state === "done" && "text-accent",
                  s.state === "current" && "bg-accent text-accent-fg",
                  s.state === "todo" && "text-muted/70",
                )}
              >
                {s.state === "done" ? "✓ " : ""}
                <span className={s.state === "current" ? "" : "hidden xl:inline"}>{s.label}</span>
                <span className={s.state === "current" ? "hidden" : "xl:hidden"}>{i + 1}</span>
              </span>
            </li>
          ))}
          {data.status === "blocked" && <Badge tone="bad">Blocked</Badge>}
          {data.status === "cancelled" && <Badge tone="warn">Cancelled</Badge>}
        </ol>
        <span className="text-muted">
          Next: <span className="text-fg">{data.next_action}</span>
          {runActive && current && <span className="ml-1">({data.run!.mode} run {data.run!.status}{data.run!.current_step ? ` · ${data.run!.current_step}` : ""})</span>}
        </span>
        {data.blockers.length > 0 && (
          <span className="text-bad" role="alert">
            {data.blockers[0]}
          </span>
        )}
        {data.run && (
          <Link to={`/decisions/${data.decision_id}/runs/${data.run.id}`} className="ml-auto text-accent hover:underline">
            Run history →
          </Link>
        )}
      </div>
    </div>
  );
}
