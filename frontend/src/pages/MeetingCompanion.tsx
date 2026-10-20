import { useState } from "react";
import type { Body } from "../api/contract";
import { Link, useParams } from "react-router-dom";
import { isDemo } from "../api/client";
import type { Meeting } from "../api/types";
import { Badge, Button, Card, ErrorState, Input, Loading, Notice, PageHeader, StatusBadge, Textarea } from "../components/ui";
import { useAction, useApi } from "../hooks/useApi";
import { MeetingCard, MeetingDialog } from "./Collaboration";

type Companion = {
  meeting: Meeting;
  decision: { id: string; title: string; status: string; question: string } | null;
  notes: { id: string; title: string; body: string }[];
  action_items: { id: string; title: string; status: string; assignee: string | null }[];
  can_edit: boolean;
};
type CommentT = { id: string; author: string; body: string; created_at: string };

/** One view beside the meeting window (Zoom, Google Meet, Teams …): agenda, shared decision, notes, action items and comments. */
export default function MeetingCompanion() {
  const { id = "" } = useParams();
  const q = useApi<Companion>(["companion", id], `/meetings/${id}/companion`, { refetchInterval: 10_000 });
  const comments = useApi<CommentT[]>(["comments", "meeting", id], `/comments?object_type=meeting&object_id=${id}`);
  const [comment, setComment] = useState("");
  const [editing, setEditing] = useState(false);
  const [note, setNote] = useState("");
  const addComment = useAction<Body<"CommentIn">>("POST", "/comments", { invalidate: [["comments", "meeting", id]], onSuccess: () => setComment("") });
  const addNote = useAction<Body<"NoteIn">>("POST", "/notes", { invalidate: [["companion", id]], onSuccess: () => setNote("") });
  const toggle = useAction<{ id: string; status: string }>("PATCH", (b) => `/action-items/${b.id}`, { invalidate: [["companion", id]] });
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorState error={q.error} />;
  const c = q.data!;
  return (
    <>
      <PageHeader title={c.meeting.title} subtitle="Meeting companion — keep this open beside the meeting window." help="zoom-meetings" />
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div className="flex flex-col gap-4">
          <MeetingCard m={c.meeting} onEdit={c.can_edit && !isDemo ? () => setEditing(true) : undefined} />
          {editing && <MeetingDialog meeting={c.meeting} onClose={() => setEditing(false)} />}
          {c.meeting.simulated && <Notice tone="warn">Simulated – no real meeting exists. The demo and Mock mode never connect a real call.</Notice>}
        </div>
        <div className="flex flex-col gap-4">
          <Card title="Agenda">
            <p className="whitespace-pre-wrap text-sm">{c.meeting.agenda || "No agenda yet."}</p>
          </Card>
          <Card title="Shared decision">
            {c.decision ? (
              <div className="text-sm">
                <Link to={c.can_edit ? `/decisions/${c.decision.id}` : `/shared/decision/${c.decision.id}`} className="font-medium text-accent hover:underline">
                  {c.decision.title}
                </Link>{" "}
                <StatusBadge status={c.decision.status} />
                <p className="mt-1 text-muted">{c.decision.question}</p>
              </div>
            ) : (
              <p className="text-sm text-muted">No decision linked (or not shared with you).</p>
            )}
          </Card>
          <Card title="Action items">
            <ul className="flex flex-col gap-1.5 text-sm">
              {c.action_items.map((a) => (
                <li key={a.id} className="flex items-center justify-between gap-2">
                  <label className="flex items-center gap-2">
                    <input type="checkbox" checked={a.status === "done"} disabled={isDemo} onChange={() => toggle.mutate({ id: a.id, status: a.status === "done" ? "open" : "done" })} />
                    <span className={a.status === "done" ? "text-muted line-through" : ""}>{a.title}</span>
                  </label>
                  <Badge>{a.assignee ?? "Owner"}</Badge>
                </li>
              ))}
            </ul>
            {toggle.error && <p className="mt-1 text-xs text-bad">{toggle.error.message}</p>}
          </Card>
        </div>
        <div className="flex flex-col gap-4">
          <Card title="Notes">
            <ul className="flex flex-col gap-2 text-sm">
              {c.notes.map((n) => (
                <li key={n.id}>
                  <p className="font-medium">{n.title}</p>
                  <p className="whitespace-pre-wrap text-muted">{n.body}</p>
                </li>
              ))}
            </ul>
            {c.can_edit && !isDemo && (
              <form
                className="mt-3 flex flex-col gap-2"
                onSubmit={(e) => {
                  e.preventDefault();
                  addNote.mutate({ title: `Meeting note ${new Date().toLocaleTimeString()}`, body: note, meeting_id: id });
                }}
              >
                <Textarea aria-label="New note" value={note} onChange={(e) => setNote(e.target.value)} placeholder="Write a note during the meeting" />
                <Button size="sm" type="submit" disabled={!note}>
                  Add note
                </Button>
              </form>
            )}
          </Card>
          <Card title="Comments">
            <ul className="flex flex-col gap-2 text-sm">
              {(comments.data ?? []).map((x) => (
                <li key={x.id}>
                  <span className="font-medium">{x.author}</span>: {x.body}
                </li>
              ))}
              {comments.data?.length === 0 && <li className="text-muted">No comments.</li>}
            </ul>
            {!isDemo && (
              <form
                className="mt-3 flex gap-2"
                onSubmit={(e) => {
                  e.preventDefault();
                  addComment.mutate({ object_type: "meeting", object_id: id, body: comment });
                }}
              >
                <Input aria-label="Comment" value={comment} onChange={(e) => setComment(e.target.value)} />
                <Button size="sm" type="submit" disabled={!comment}>
                  Post
                </Button>
              </form>
            )}
            {addComment.error && <p className="mt-1 text-xs text-bad">{addComment.error.message}</p>}
          </Card>
        </div>
      </div>
    </>
  );
}
