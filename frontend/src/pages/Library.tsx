import { useQueryClient } from "@tanstack/react-query";
import type { Body } from "../api/contract";
import { useRef, useState } from "react";
import { ApiError, api, get, isDemo, post } from "../api/client";
import type { Answer, LibraryDoc } from "../api/types";
import { Badge, Button, Card, Dialog, EmptyState, ErrorState, Input, Loading, Notice, OutputBadge, PageHeader, StatusBadge, Table, Td, TextField, Th } from "../components/ui";
import { useApi, withStepUp } from "../hooks/useApi";
import { fmtTime } from "../lib/format";

type Status = { embeddings: { enabled: boolean; state: string; message?: string }; quota_bytes: number; used_bytes: number; max_file_bytes: number; allowed_types: string[]; documents: number };
type Preview = {
  document_id: string; title: string; affected_decisions: number; snapshot_items: number; derived_records: number; active_shares: number;
  stored_exports: { id: string; created_at: string }[]; backup_retention_days: number; backups_clear_after: string; erase_phrase: string;
  choices: { remove: string; erase: string; cannot_recall: string; backups: string };
};

export function AnswerView({ a }: { a: Answer }) {
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <OutputBadge label={a.label === "Model-generated" ? "model" : "computed"} detail={a.model?.model} />
        <Badge>{a.mode === "extractive" ? "Extractive: verbatim passages" : a.mode === "generated" ? "Generated with citations" : "Abstained"}</Badge>
        <Badge tone="computed">Retrieval: {a.retrieval.method === "hybrid" ? "keyword + embeddings" : "keyword search only"}</Badge>
      </div>
      {a.retrieval.model_error && <Notice tone="warn">Model unavailable ({a.retrieval.model_error}); showing extractive answer instead.</Notice>}
      {a.mode === "abstained" && <Notice title="Not found in your library">No passage was relevant enough to answer. Nothing was generated.</Notice>}
      <ol className="flex flex-col gap-2">
        {a.statements.map((s, i) => (
          <li key={i} className={s.kind === "quote" ? "border-l-2 border-accent/50 pl-3" : "rounded bg-surface-2 p-2"}>
            <p className="text-[11px] uppercase tracking-wide text-muted">{s.kind === "quote" ? "Retrieved evidence (verbatim)" : "Interpretation"}</p>
            <p className="text-sm">{s.kind === "quote" ? `“${s.text}”` : s.text}</p>
            <p className="mt-0.5 text-xs text-muted">
              {s.citations.map((c) => (a.citations[c] ? `${a.citations[c].document_title} (${a.citations[c].location})` : "invalid citation")).join(" · ")}
            </p>
            {s.flags.map((f, j) => (
              <p key={j} className="text-xs text-warn">
                ⚠ {f}
              </p>
            ))}
          </li>
        ))}
      </ol>
      <div className="rounded border border-line p-3">
        <p className="mb-1 text-xs font-medium">Evidence checks</p>
        <ul className="grid grid-cols-1 gap-1 text-xs sm:grid-cols-2">
          {a.checks.map((c) => (
            <li key={c.key}>
              <span className={c.passed ? "text-good" : "text-bad"}>{c.passed ? "✓" : "✗"}</span> {c.name} {c.heuristic && <Badge>heuristic</Badge>}
              <span className="block text-muted">{c.detail}</span>
            </li>
          ))}
        </ul>
        <p className="mt-2 text-[11px] text-muted">{a.disclaimer}</p>
      </div>
    </div>
  );
}

export default function Library() {
  const qc = useQueryClient();
  const status = useApi<Status>(["library-status"], "/library/status");
  const docs = useApi<LibraryDoc[]>(["library"], "/library/documents", { refetchInterval: (q) => (q.state.data?.some((d) => ["uploaded", "parsing"].includes(d.status)) ? 2000 : 30_000) });
  const agents = useApi<{ modes: { model: boolean } }>(["agents"], "/agents/status");
  const fileRef = useRef<HTMLInputElement>(null);
  const [uploadError, setUploadError] = useState<ApiError | null>(null);
  const [uploading, setUploading] = useState(false);
  const [question, setQuestion] = useState("");
  const [useModel, setUseModel] = useState(false);
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [asking, setAsking] = useState(false);
  const [askError, setAskError] = useState<ApiError | null>(null);
  const [deleting, setDeleting] = useState<LibraryDoc | null>(null);

  const upload = async (file: File) => {
    setUploading(true);
    setUploadError(null);
    try {
      const form = new FormData();
      form.append("file", file);
      await api("/library/documents", { form });
      qc.invalidateQueries({ queryKey: ["library"] });
      qc.invalidateQueries({ queryKey: ["library-status"] });
    } catch (e) {
      setUploadError(e as ApiError);
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };
  const ask = async () => {
    setAsking(true);
    setAskError(null);
    try {
      setAnswer(await get<Answer>(`/library/ask?q=${encodeURIComponent(question)}&use_model=${useModel}`));
    } catch (e) {
      setAskError(e as ApiError);
    } finally {
      setAsking(false);
    }
  };
  const s = status.data;
  return (
    <>
      <PageHeader title="Knowledge library" subtitle="Local, access-scoped retrieval over your documents. Answers cite exact locations and separate evidence from interpretation." help="knowledge-library" />
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_440px]">
        <div className="flex flex-col gap-4">
          <Card title="Ask your library" help="knowledge-library">
            <form
              className="flex flex-col gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                if (question.trim().length >= 3) ask();
              }}
            >
              <Input aria-label="Question" placeholder="e.g. What are the risks of export restrictions?" value={question} onChange={(e) => setQuestion(e.target.value)} />
              <div className="flex flex-wrap items-center justify-between gap-2">
                <label className={`flex items-center gap-2 text-sm ${agents.data?.modes.model && !isDemo ? "" : "opacity-60"}`}>
                  <input type="checkbox" checked={useModel} disabled={!agents.data?.modes.model || isDemo} onChange={(e) => setUseModel(e.target.checked)} />
                  Generate an answer with the local model (citations still checked)
                </label>
                <Button type="submit" variant="primary" busy={asking}>
                  Ask
                </Button>
              </div>
            </form>
            <div className="mt-3">
              <ErrorState error={askError} />
              {answer && <AnswerView a={answer} />}
            </div>
          </Card>
          <Card
            title="Documents"
            actions={
              !isDemo && (
                <>
                  <input ref={fileRef} type="file" className="sr-only" id="upload" accept=".pdf,.md,.markdown,.txt,.csv" onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
                  <label htmlFor="upload" className="cursor-pointer rounded-md bg-accent px-3 py-1.5 text-xs font-medium text-accent-fg hover:opacity-90">
                    {uploading ? "Uploading…" : "Upload"}
                  </label>
                  <Button size="sm" onClick={() => post("/library/reindex").then(() => qc.invalidateQueries({ queryKey: ["library"] }))}>
                    Re-index all
                  </Button>
                </>
              )
            }
          >
            <ErrorState error={uploadError} />
            {docs.isLoading && <Loading />}
            {docs.data?.length === 0 && <EmptyState title="No documents yet">Upload text-based PDF, Markdown, plain text or CSV files.</EmptyState>}
            {(docs.data ?? []).length > 0 && (
              <Table caption="Documents">
                <thead>
                  <tr>
                    <Th>Title</Th>
                    <Th>Type</Th>
                    <Th right>Passages</Th>
                    <Th>Status</Th>
                    <Th>Added</Th>
                    <Th />
                  </tr>
                </thead>
                <tbody>
                  {docs.data!.map((d) => (
                    <tr key={d.id}>
                      <Td>
                        {d.title}
                        {d.error && <span className="block text-xs text-bad">{d.error}</span>}
                      </Td>
                      <Td>{d.file_type}</Td>
                      <Td right>{d.chunk_count}</Td>
                      <Td>
                        <StatusBadge status={d.status === "ready" ? "fresh" : d.status === "failed" ? "failed" : "queued"} label={d.status} />
                      </Td>
                      <Td>{fmtTime(d.created_at)}</Td>
                      <Td>
                        {!isDemo && (
                          <span className="flex gap-1">
                            <Button size="sm" variant="ghost" onClick={() => post(`/library/documents/${d.id}/reindex`).then(() => qc.invalidateQueries({ queryKey: ["library"] }))}>
                              Re-index
                            </Button>
                            <Button size="sm" variant="ghost" onClick={() => setDeleting(d)}>
                              Delete…
                            </Button>
                          </span>
                        )}
                      </Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            )}
          </Card>
        </div>
        <div className="flex flex-col gap-4">
          <Card title="Library status">
            {s && (
              <ul className="flex flex-col gap-1.5 text-sm">
                <li>
                  Retrieval: <Badge tone={s.embeddings.state === "ready" ? "good" : "neutral"}>{s.embeddings.state === "ready" ? "keyword + embeddings" : "keyword search only"}</Badge>
                  {s.embeddings.message && <span className="block text-xs text-muted">{s.embeddings.message}</span>}
                </li>
                <li>
                  Storage: {(s.used_bytes / 1048576).toFixed(1)} MB of {(s.quota_bytes / 1073741824).toFixed(0)} GB
                </li>
                <li>
                  Allowed: {s.allowed_types.join(", ").toUpperCase()} · max {(s.max_file_bytes / 1048576).toFixed(0)} MB per file
                </li>
              </ul>
            )}
          </Card>
          <Notice title="Checks are heuristics">Citation checks confirm that cited passages exist and quotes match. They cannot prove that a source supports a claim. Read the passage before relying on it.</Notice>
          <Notice title="Untrusted content">Document text is treated as data. Instructions inside documents cannot change what the agents may do.</Notice>
        </div>
      </div>
      {deleting && <DeleteDialog doc={deleting} onClose={() => setDeleting(null)} />}
    </>
  );
}

export function DeleteDialog({ doc, onClose }: { doc: LibraryDoc; onClose: () => void }) {
  const qc = useQueryClient();
  const preview = useApi<Preview>(["deletion-preview", doc.id], `/library/documents/${doc.id}/deletion-preview`);
  const [mode, setMode] = useState<"remove" | "erase">("remove");
  const [phrase, setPhrase] = useState("");
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const p = preview.data;
  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      await withStepUp(() => post(`/library/documents/${doc.id}/delete`, { mode, confirm_phrase: mode === "erase" ? phrase : undefined } satisfies Body<"DeleteIn">));
      qc.invalidateQueries();
      onClose();
    } catch (e) {
      setError(e as ApiError);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()} title={`Delete “${doc.title}”`} description="Both choices are irreversible. Read the effects first." wide>
      {preview.isLoading && <Loading />}
      {p && (
        <div className="flex flex-col gap-3 text-sm">
          <ul className="grid grid-cols-2 gap-2 text-xs">
            <li className="rounded border border-line p-2">Affected decisions: <strong>{p.affected_decisions}</strong></li>
            <li className="rounded border border-line p-2">Frozen evidence items: <strong>{p.snapshot_items}</strong></li>
            <li className="rounded border border-line p-2">Derived copies (agent outputs, answers): <strong>{p.derived_records}</strong></li>
            <li className="rounded border border-line p-2">Active shares: <strong>{p.active_shares}</strong> · stored exports: <strong>{p.stored_exports.length}</strong></li>
          </ul>
          <fieldset className="flex flex-col gap-2">
            <legend className="sr-only">Deletion choice</legend>
            <label className={`flex gap-2 rounded border p-3 ${mode === "remove" ? "border-accent" : "border-line"}`}>
              <input type="radio" name="mode" checked={mode === "remove"} onChange={() => setMode("remove")} />
              <span>
                <strong>1. Remove from Library</strong>
                <span className="block text-muted">{p.choices.remove}</span>
              </span>
            </label>
            <label className={`flex gap-2 rounded border p-3 ${mode === "erase" ? "border-bad" : "border-line"}`}>
              <input type="radio" name="mode" checked={mode === "erase"} onChange={() => setMode("erase")} />
              <span>
                <strong>2. Fully erase content</strong>
                <span className="block text-muted">{p.choices.erase}</span>
              </span>
            </label>
          </fieldset>
          <p className="text-xs text-muted">{p.choices.cannot_recall}</p>
          <p className="text-xs text-muted">
            {p.choices.backups} Backups clear after about {p.backups_clear_after}.
          </p>
          {mode === "erase" && <TextField label={`Type ${p.erase_phrase} to confirm (you will also confirm your password)`} value={phrase} onChange={(e) => setPhrase(e.target.value)} />}
          <ErrorState error={error} />
          <div className="flex justify-end gap-2">
            <Button onClick={onClose}>Keep document</Button>
            <Button variant="danger" busy={busy} disabled={mode === "erase" && phrase !== p.erase_phrase} onClick={run}>
              {mode === "erase" ? "Erase permanently" : "Remove from Library"}
            </Button>
          </div>
        </div>
      )}
    </Dialog>
  );
}
