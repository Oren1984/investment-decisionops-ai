import { useState } from "react";
import type { Body } from "../api/contract";
import { Link, Route, Routes, useParams } from "react-router-dom";
import { get } from "../api/client";
import type { Answer, Meeting, Snapshot } from "../api/types";
import { EvidenceView } from "../components/Evidence";
import { Badge, Button, Card, EmptyState, ErrorState, Input, Loading, Notice, PageHeader } from "../components/ui";
import { useAction, useApi } from "../hooks/useApi";
import type { ApiError } from "../api/client";
import { AnswerView } from "./Library";
import { MeetingCard } from "./Collaboration";

type SharedItem = { object_type: string; object_id: string; title: string; permission: string };

export default function Shared() {
  return (
    <Routes>
      <Route index element={<SharedHome />} />
      <Route path="decision/:id" element={<SharedDecision />} />
      <Route path="document/:id" element={<SharedDocument />} />
      <Route path="note/:id" element={<SharedNote />} />
      <Route path="meeting/:id" element={<SharedHome />} />
    </Routes>
  );
}

function SharedHome() {
  const q = useApi<SharedItem[]>(["shared"], "/shared", { refetchInterval: 15_000 });
  const meetings = useApi<Meeting[]>(["meetings"], "/meetings");
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  return (
    <>
      <PageHeader title="Shared with me" subtitle="Only material the owner explicitly shared. Access ends immediately when it is revoked." help="collaboration-and-sharing" />
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card title="Items">
          {q.isLoading && <Loading />}
          {q.data?.length === 0 && <EmptyState title="Nothing is shared with you yet" />}
          <ul className="flex flex-col gap-2 text-sm">
            {(q.data ?? []).map((s) => (
              <li key={`${s.object_type}-${s.object_id}`} className="flex items-center justify-between gap-2">
                <Link to={s.object_type === "meeting" ? `/meetings/${s.object_id}` : `/shared/${s.object_type}/${s.object_id}`} className="hover:underline">
                  <Badge>{s.object_type}</Badge> {s.title}
                </Link>
                <Badge tone={s.permission === "comment" ? "accent" : "neutral"}>{s.permission}</Badge>
              </li>
            ))}
          </ul>
        </Card>
        <Card title="Meetings">
          <div className="flex flex-col gap-3">
            {(meetings.data ?? []).map((m) => (
              <MeetingCard key={m.id} m={m} />
            ))}
            {meetings.data?.length === 0 && <p className="text-sm text-muted">No shared meetings.</p>}
          </div>
        </Card>
        <Card title="Search shared documents">
          <form
            className="flex gap-2"
            onSubmit={async (e) => {
              e.preventDefault();
              setError(null);
              try {
                setAnswer(await get<Answer>(`/shared/library/ask?q=${encodeURIComponent(question)}`));
              } catch (err) {
                setError(err as ApiError);
              }
            }}
          >
            <Input aria-label="Question" value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="Ask about documents shared with you" />
            <Button type="submit">Ask</Button>
          </form>
          <div className="mt-3">
            <ErrorState error={error} />
            {answer && <AnswerView a={answer} />}
          </div>
        </Card>
      </div>
    </>
  );
}

function Comments({ type, id, canComment }: { type: Body<"CommentIn">["object_type"]; id: string; canComment: boolean }) {
  const q = useApi<{ id: string; author: string; body: string; created_at: string }[]>(["comments", type, id], `/comments?object_type=${type}&object_id=${id}`);
  const [body, setBody] = useState("");
  const add = useAction<Body<"CommentIn">>("POST", "/comments", { invalidate: [["comments", type, id]], onSuccess: () => setBody("") });
  return (
    <Card title="Comments">
      <ul className="flex flex-col gap-2 text-sm">
        {(q.data ?? []).map((c) => (
          <li key={c.id}>
            <span className="font-medium">{c.author}</span>: {c.body}
          </li>
        ))}
        {q.data?.length === 0 && <li className="text-muted">No comments yet.</li>}
      </ul>
      {canComment ? (
        <form
          className="mt-3 flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            add.mutate({ object_type: type, object_id: id, body });
          }}
        >
          <Input aria-label="Comment" value={body} onChange={(e) => setBody(e.target.value)} />
          <Button type="submit" disabled={!body}>
            Post
          </Button>
        </form>
      ) : (
        <p className="mt-2 text-xs text-muted">View-only access.</p>
      )}
      {add.error && <p className="mt-1 text-xs text-bad">{add.error.message}</p>}
    </Card>
  );
}

function SharedDecision() {
  const { id = "" } = useParams();
  const q = useApi<{ decision: { title: string; question: string; status: string; outcome: string | null }; version: { version_no: number; outcome: string; rationale: string } | null; evidence: Snapshot | null; can_comment: boolean }>(
    ["shared-decision", id], `/shared/decisions/${id}`,
  );
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorState error={q.error} />;
  const d = q.data!;
  return (
    <>
      <PageHeader title={d.decision.title} subtitle={d.decision.question} />
      <div className="mb-4">
        <Notice>Shared view: raw market quotes and portfolio totals are withheld unless the owner chose to include portfolio context.</Notice>
      </div>
      {d.version && (
        <Card title={`Owner decision v${d.version.version_no}: ${d.version.outcome}`}>
          <p className="text-sm">{d.version.rationale}</p>
        </Card>
      )}
      <div className="mt-4">{d.evidence ? <EvidenceView snapshot={d.evidence} /> : <EmptyState title="No evidence package yet" />}</div>
      <div className="mt-4">
        <Comments type="decision" id={id} canComment={d.can_comment} />
      </div>
    </>
  );
}

function SharedDocument() {
  const { id = "" } = useParams();
  const q = useApi<{ title: string; chunks: { page: number | null; section: string | null; text: string }[]; can_comment: boolean }>(["shared-doc", id], `/shared/documents/${id}`);
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorState error={q.error} />;
  return (
    <>
      <PageHeader title={q.data!.title} />
      <Card>
        {q.data!.chunks.map((c, i) => (
          <div key={i} className="mb-3">
            <p className="text-xs text-muted">{[c.page && `p. ${c.page}`, c.section].filter(Boolean).join(" · ")}</p>
            <p className="text-sm">{c.text}</p>
          </div>
        ))}
      </Card>
      <div className="mt-4">
        <Comments type="document" id={id} canComment={q.data!.can_comment} />
      </div>
    </>
  );
}

function SharedNote() {
  const { id = "" } = useParams();
  const q = useApi<{ title: string; body: string; can_comment: boolean }>(["shared-note", id], `/shared/notes/${id}`);
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorState error={q.error} />;
  return (
    <>
      <PageHeader title={q.data!.title} />
      <Card>
        <p className="whitespace-pre-wrap text-sm">{q.data!.body}</p>
      </Card>
      <div className="mt-4">
        <Comments type="note" id={id} canComment={q.data!.can_comment} />
      </div>
    </>
  );
}
