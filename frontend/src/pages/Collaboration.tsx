import { useState } from "react";
import type { Body } from "../api/contract";
import { Link } from "react-router-dom";
import { isDemo } from "../api/client";
import type { DecisionSummary, LibraryDoc, Meeting } from "../api/types";
import { Badge, Button, buttonClass, Card, Dialog, EmptyState, Field, Input, Loading, Notice, PageHeader, Select, StatusBadge, Tabs, Textarea, TextField } from "../components/ui";
import { useAction, useApi } from "../hooks/useApi";
import { fmtTime } from "../lib/format";

type Person = { id: string; email: string; display_name: string; timezone: string; active: boolean; active_shares: number };
type Invite = { id: string; email: string; display_name: string; state: string; expires_at: string; accept_path?: string };
type Share = { id: string; object_type: string; object_id: string; object_title: string; grantee_name: string; permission: string; state: string; include_portfolio_context: boolean; expires_at: string | null };
type NoteT = { id: string; title: string; body: string; meeting_id: string | null; updated_at: string; redacted: boolean };
type Action = { id: string; title: string; status: string; assignee: string | null; due_at: string | null; meeting_id: string | null };

const ZONES = ["Asia/Jerusalem", "Europe/London", "Europe/Berlin", "America/New_York", "Asia/Tokyo", "Asia/Shanghai", "Asia/Singapore", "Australia/Sydney", "UTC"];

export default function Collaboration() {
  return (
    <>
      <PageHeader title="Collaboration" subtitle="Share selected material with your brokers or traders. They see only what you share; revocation is immediate." help="collaboration-and-sharing" />
      <Tabs
        tabs={[
          { value: "meetings", label: "Meetings", content: <MeetingsTab /> },
          { value: "people", label: "People", content: <PeopleTab /> },
          { value: "shares", label: "Shares", content: <SharesTab /> },
          { value: "notes", label: "Notes", content: <NotesTab /> },
          { value: "actions", label: "Action items", content: <ActionsTab /> },
        ]}
      />
    </>
  );
}

function PeopleTab() {
  const people = useApi<Person[]>(["people"], "/people");
  const invites = useApi<Invite[]>(["invites"], "/invitations");
  const [form, setForm] = useState({ email: "", display_name: "", timezone: "Europe/London" });
  const [created, setCreated] = useState<Invite | null>(null);
  const invite = useAction<Body<"InviteIn">, Invite>("POST", "/invitations", { invalidate: [["invites"]], onSuccess: (r) => setCreated(r) });
  const revoke = useAction<{ id: string }>("POST", (b) => `/people/${b.id}/revoke`, { invalidate: [["people"], ["shares"]] });
  const revokeInvite = useAction<{ id: string }>("DELETE", (b) => `/invitations/${b.id}`, { invalidate: [["invites"]] });
  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <Card title="Collaborators">
        {people.isLoading && <Loading />}
        {people.data?.length === 0 && <EmptyState title="No collaborators yet" />}
        <ul className="flex flex-col gap-2 text-sm">
          {(people.data ?? []).map((p) => (
            <li key={p.id} className="flex items-center justify-between gap-2">
              <span>
                {p.display_name} <span className="text-xs text-muted">· {p.email} · {p.timezone}</span>
                <span className="block text-xs text-muted">{p.active_shares} active share(s)</span>
              </span>
              {p.active ? (
                !isDemo && (
                  <Button size="sm" variant="danger" onClick={() => revoke.mutate({ id: p.id })}>
                    Revoke access
                  </Button>
                )
              ) : (
                <Badge tone="bad">revoked</Badge>
              )}
            </li>
          ))}
        </ul>
      </Card>
      <Card title="Invite a broker or trader">
        {!isDemo && (
          <form
            className="flex flex-col gap-3"
            onSubmit={(e) => {
              e.preventDefault();
              invite.mutate(form);
            }}
          >
            <TextField label="Name" value={form.display_name} onChange={(e) => setForm({ ...form, display_name: e.target.value })} required />
            <TextField label="Email" type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} required />
            <Field label="Their timezone" htmlFor="itz">
              <Select id="itz" value={form.timezone} onChange={(e) => setForm({ ...form, timezone: e.target.value })}>
                {ZONES.map((z) => (
                  <option key={z}>{z}</option>
                ))}
              </Select>
            </Field>
            {invite.error && <p className="text-sm text-bad">{invite.error.message}</p>}
            <Button type="submit" variant="primary" busy={invite.isPending}>
              Create invitation link
            </Button>
          </form>
        )}
        {created?.accept_path && (
          <Notice tone="accent" title="Invitation link (shown once)">
            <code className="break-all text-xs">{window.location.origin + created.accept_path}</code>
            <p className="mt-1 text-xs">Send it to them yourself. No email is sent by this app.</p>
          </Notice>
        )}
        <ul className="mt-4 flex flex-col gap-1.5 text-sm">
          {(invites.data ?? []).map((i) => (
            <li key={i.id} className="flex items-center justify-between gap-2">
              <span>
                {i.display_name} <span className="text-xs text-muted">· {i.email}</span>
              </span>
              <span className="flex items-center gap-2">
                <StatusBadge status={i.state === "pending" ? "pending_approval" : i.state} label={i.state} />
                {i.state === "pending" && !isDemo && (
                  <Button size="sm" variant="ghost" onClick={() => revokeInvite.mutate({ id: i.id })}>
                    Revoke
                  </Button>
                )}
              </span>
            </li>
          ))}
        </ul>
      </Card>
    </div>
  );
}

function SharesTab() {
  const shares = useApi<Share[]>(["shares"], "/shares");
  const people = useApi<Person[]>(["people"], "/people");
  const decisions = useApi<DecisionSummary[]>(["decisions"], "/decisions");
  const docs = useApi<LibraryDoc[]>(["library"], "/library/documents");
  const notes = useApi<NoteT[]>(["notes"], "/notes");
  const meetings = useApi<Meeting[]>(["meetings"], "/meetings");
  const [f, setF] = useState<Body<"ShareIn">>({ object_type: "decision", object_id: "", grantee_id: "", permission: "view", include_portfolio_context: false });
  const create = useAction<Body<"ShareIn">>("POST", "/shares", { invalidate: [["shares"], ["people"]] });
  const revoke = useAction<{ id: string }>("DELETE", (b) => `/shares/${b.id}`, { invalidate: [["shares"], ["people"]] });
  const objects: Record<string, { id: string; title: string }[]> = {
    decision: decisions.data ?? [], document: docs.data ?? [], note: notes.data ?? [], meeting: meetings.data ?? [],
  };
  const activePeople = (people.data ?? []).filter((p) => p.active);
  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_380px]">
      <Card title="Shares">
        <Notice>Portfolio totals, orders, broker data and settings are never shared. Raw quote data is withheld from shared decisions (market-data licensing).</Notice>
        <ul className="mt-3 flex flex-col gap-2 text-sm">
          {(shares.data ?? []).map((s) => (
            <li key={s.id} className="flex flex-wrap items-center justify-between gap-2 border-b border-line/50 pb-1.5">
              <span>
                <Badge>{s.object_type}</Badge> {s.object_title} → {s.grantee_name} <Badge>{s.permission}</Badge>
                {s.include_portfolio_context && <Badge tone="warn">incl. portfolio context</Badge>}
              </span>
              <span className="flex items-center gap-2">
                <StatusBadge status={s.state} />
                {s.state === "active" && !isDemo && (
                  <Button size="sm" variant="danger" onClick={() => revoke.mutate({ id: s.id })}>
                    Revoke now
                  </Button>
                )}
              </span>
            </li>
          ))}
          {shares.data?.length === 0 && <li className="text-muted">Nothing shared yet.</li>}
        </ul>
      </Card>
      {!isDemo && (
        <Card title="Share something">
          <form
            className="flex flex-col gap-3"
            onSubmit={(e) => {
              e.preventDefault();
              create.mutate(f);
            }}
          >
            <Field label="Type" htmlFor="st">
              <Select id="st" value={f.object_type} onChange={(e) => setF({ ...f, object_type: e.target.value as Body<"ShareIn">["object_type"], object_id: "" })}>
                <option value="decision">Decision (frozen evidence)</option>
                <option value="document">Library document</option>
                <option value="note">Note</option>
                <option value="meeting">Meeting (agenda, notes, action items)</option>
              </Select>
            </Field>
            <Field label="Item" htmlFor="so">
              <Select id="so" value={f.object_id} onChange={(e) => setF({ ...f, object_id: e.target.value })} required>
                <option value="">Choose…</option>
                {objects[f.object_type].map((o) => (
                  <option key={o.id} value={o.id}>
                    {o.title}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="With" htmlFor="sg">
              <Select id="sg" value={f.grantee_id} onChange={(e) => setF({ ...f, grantee_id: e.target.value })} required>
                <option value="">Choose…</option>
                {activePeople.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.display_name}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Permission" htmlFor="sp">
              <Select id="sp" value={f.permission} onChange={(e) => setF({ ...f, permission: e.target.value as Body<"ShareIn">["permission"] })}>
                <option value="view">View</option>
                <option value="comment">View and comment</option>
              </Select>
            </Field>
            {f.object_type === "decision" && (
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={f.include_portfolio_context} onChange={(e) => setF({ ...f, include_portfolio_context: e.target.checked })} /> Include portfolio context (off by default)
              </label>
            )}
            {create.error && <p className="text-sm text-bad">{create.error.message}</p>}
            <Button type="submit" variant="primary" busy={create.isPending} disabled={!f.object_id || !f.grantee_id}>
              Share
            </Button>
          </form>
        </Card>
      )}
    </div>
  );
}

function MeetingsTab() {
  const meetings = useApi<Meeting[]>(["meetings"], "/meetings");
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<Meeting | null>(null);
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-muted">Add a Zoom, Google Meet, Microsoft Teams or other https meeting link; “Open meeting” opens it in a new tab. The companion page keeps agenda, decision, notes and action items beside it. Meetings are never recorded by this app.</p>
        {!isDemo && (
          <Button variant="primary" onClick={() => setOpen(true)}>
            Schedule meeting
          </Button>
        )}
      </div>
      {meetings.isLoading && <Loading />}
      {meetings.data?.length === 0 && <EmptyState title="No meetings scheduled" />}
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        {(meetings.data ?? []).map((m) => (
          <MeetingCard key={m.id} m={m} onEdit={isDemo ? undefined : () => setEditing(m)} />
        ))}
      </div>
      {open && <MeetingDialog onClose={() => setOpen(false)} />}
      {editing && <MeetingDialog meeting={editing} onClose={() => setEditing(null)} />}
    </div>
  );
}

type LinkProvider = NonNullable<Body<"MeetingIn">["link_provider"]>;
const LINK_PROVIDERS: { value: LinkProvider; label: string; placeholder: string }[] = [
  { value: "zoom", label: "Zoom", placeholder: "https://zoom.us/j/…" },
  { value: "google_meet", label: "Google Meet", placeholder: "https://meet.google.com/abc-defg-hij" },
  { value: "teams", label: "Microsoft Teams", placeholder: "https://teams.microsoft.com/l/meetup-join/…" },
  { value: "other", label: "Other (any https link)", placeholder: "https://…" },
];

/** Only plain https links are ever rendered as a link (the server validates too). */
export function safeMeetingUrl(url: string | null): string | null {
  if (!url) return null;
  try {
    return new URL(url).protocol === "https:" ? url : null;
  } catch {
    return null;
  }
}

export function MeetingCard({ m, onEdit }: { m: Meeting; onEdit?: () => void }) {
  const href = safeMeetingUrl(m.join_url);
  const service = m.link_provider && m.link_provider !== "other" ? m.link_provider_label : null;
  return (
    <Card title={m.title} actions={<StatusBadge status={m.provider_status} label={m.provider === "mock" ? "simulated" : m.provider_status} />}>
      <ul className="flex flex-col gap-1 text-sm">
        <li>
          <span className="text-muted">Owner time:</span> {m.owner_time.label} <span className="text-xs text-muted">({m.owner_time.timezone}, UTC{m.owner_time.utc_offset})</span>
        </li>
        {m.participants.map((p) => (
          <li key={p.id}>
            <span className="text-muted">{p.name}:</span> {p.time.label} <span className="text-xs text-muted">({p.time.timezone}, UTC{p.time.utc_offset})</span>
            {p.time.day_shift !== 0 && <Badge tone="accent" className="ml-1">{p.time.day_shift > 0 ? "+1 day" : "−1 day"}</Badge>}
          </li>
        ))}
        {m.link_provider_label && (
          <li>
            <span className="text-muted">Meeting service:</span> {m.link_provider === "other" ? "Other link" : m.link_provider_label}
          </li>
        )}
      </ul>
      <p className="mt-2 text-xs text-muted">{m.provider_note}</p>
      {m.provider_error && <p className="mt-1 text-xs text-bad">{m.provider_error}</p>}
      <div className="mt-3 flex flex-wrap gap-2">
        <Link to={`/meetings/${m.id}`} className={buttonClass("secondary", "sm")}>
          Open companion page
        </Link>
        {href ? (
          <a href={href} target="_blank" rel="noopener noreferrer" className={buttonClass("primary", "sm")} aria-label={`Open meeting${service ? ` in ${service}` : ""} (opens in a new tab)`}>
            Open meeting ↗
          </a>
        ) : (
          m.simulated && <Badge tone="warn">Simulated – no real meeting exists</Badge>
        )}
        {onEdit && (
          <Button size="sm" variant="ghost" onClick={onEdit}>
            Edit meeting
          </Button>
        )}
      </div>
    </Card>
  );
}

export function MeetingDialog({ onClose, meeting }: { onClose: () => void; meeting?: Meeting }) {
  const people = useApi<Person[]>(["people"], "/people");
  const decisions = useApi<DecisionSummary[]>(["decisions"], "/decisions");
  const tomorrow = new Date(Date.now() + 86400_000);
  tomorrow.setMinutes(0, 0, 0);
  const start = meeting ? new Date(meeting.starts_at) : tomorrow;
  const local = new Date(start.getTime() - start.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  const [f, setF] = useState<{ title: string; when: string; duration_minutes: number; provider: Body<"MeetingIn">["provider"]; link_provider: LinkProvider; join_url: string; agenda: string; decision_id: string; timezone: string }>({
    title: meeting?.title ?? "",
    when: local,
    duration_minutes: meeting?.duration_minutes ?? 30,
    provider: meeting?.provider ?? "mock",
    link_provider: meeting?.link_provider ?? "zoom",
    join_url: meeting?.provider === "manual" ? (meeting.join_url ?? "") : "",
    agenda: meeting?.agenda ?? "",
    decision_id: meeting?.decision_id ?? "",
    timezone: meeting?.timezone ?? Intl.DateTimeFormat().resolvedOptions().timeZone,
  });
  const [parts, setParts] = useState<{ name: string; timezone: string; user_id?: string }[]>(
    meeting?.participants.map((p) => ({ name: p.name, timezone: p.time.timezone, ...(p.user_id ? { user_id: p.user_id } : {}) })) ?? [],
  );
  const save = useAction<Body<"MeetingIn">>(meeting ? "PUT" : "POST", meeting ? `/meetings/${meeting.id}` : "/meetings", {
    invalidate: meeting ? [["meetings"], ["companion", meeting.id]] : [["meetings"]],
    onSuccess: onClose,
  });
  const linkInfo = LINK_PROVIDERS.find((p) => p.value === f.link_provider) ?? LINK_PROVIDERS[0];
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()} title={meeting ? "Edit meeting" : "Schedule a meeting"} description="Times are stored in UTC and shown in each participant's timezone." wide>
      <form
        className="grid grid-cols-1 gap-3 sm:grid-cols-2"
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate({
            title: f.title,
            duration_minutes: f.duration_minutes,
            provider: f.provider,
            link_provider: f.provider === "manual" ? f.link_provider : null,
            agenda: f.agenda,
            timezone: f.timezone,
            starts_at: new Date(f.when).toISOString(),
            decision_id: f.decision_id || null,
            join_url: f.provider === "manual" ? f.join_url.trim() || null : null,
            participants: parts,
          });
        }}
      >
        <div className="sm:col-span-2">
          <TextField label="Title" value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} required />
        </div>
        <TextField label={`Start (${f.timezone})`} type="datetime-local" value={f.when} onChange={(e) => setF({ ...f, when: e.target.value })} required />
        <TextField label="Duration (minutes)" type="number" min={5} max={480} value={f.duration_minutes} onChange={(e) => setF({ ...f, duration_minutes: Number(e.target.value) })} />
        <Field label="Meeting type" htmlFor="prov">
          <Select id="prov" value={f.provider} onChange={(e) => setF({ ...f, provider: e.target.value as Body<"MeetingIn">["provider"] })}>
            <option value="mock">Simulated (no real meeting)</option>
            <option value="manual">Meeting link (Zoom, Google Meet, Teams, other)</option>
            <option value="zoom">Schedule through Zoom API (if configured)</option>
          </Select>
        </Field>
        {f.provider === "manual" && (
          <>
            <Field label="Meeting provider" htmlFor="lprov">
              <Select id="lprov" value={f.link_provider} onChange={(e) => setF({ ...f, link_provider: e.target.value as LinkProvider })}>
                {LINK_PROVIDERS.map((p) => (
                  <option key={p.value} value={p.value}>
                    {p.label}
                  </option>
                ))}
              </Select>
            </Field>
            <div className="sm:col-span-2">
              <TextField
                label="Meeting link"
                type="url"
                inputMode="url"
                autoComplete="off"
                placeholder={linkInfo.placeholder}
                value={f.join_url}
                onChange={(e) => setF({ ...f, join_url: e.target.value })}
                required
              />
              <p className="mt-1 text-xs text-muted">Only https links. “Open meeting” opens it in a new browser tab; nothing is embedded or recorded.</p>
            </div>
          </>
        )}
<Field label="Linked decision" htmlFor="md">
          <Select id="md" value={f.decision_id} onChange={(e) => setF({ ...f, decision_id: e.target.value })}>
            <option value="">None</option>
            {(decisions.data ?? []).map((d) => (
              <option key={d.id} value={d.id}>
                {d.title}
              </option>
            ))}
          </Select>
        </Field>
        <div className="sm:col-span-2">
          <Field label="Agenda" htmlFor="ag">
            <Textarea id="ag" value={f.agenda} onChange={(e) => setF({ ...f, agenda: e.target.value })} />
          </Field>
        </div>
        <div className="sm:col-span-2">
          <p className="mb-1 text-xs font-medium text-muted">Participants</p>
          {parts.map((p, i) => (
            <div key={i} className="mb-1 grid grid-cols-[minmax(0,1fr)_1fr_auto] gap-2">
              <Input aria-label="Participant name" value={p.name} onChange={(e) => setParts(parts.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)))} />
              <Select aria-label="Participant timezone" value={p.timezone} onChange={(e) => setParts(parts.map((x, j) => (j === i ? { ...x, timezone: e.target.value } : x)))}>
                {ZONES.map((z) => (
                  <option key={z}>{z}</option>
                ))}
              </Select>
              <Button type="button" size="sm" variant="ghost" onClick={() => setParts(parts.filter((_, j) => j !== i))} aria-label="Remove participant">
                ✕
              </Button>
            </div>
          ))}
          <div className="flex flex-wrap gap-2">
            {(people.data ?? []).filter((p) => p.active).map((p) => (
              <Button key={p.id} type="button" size="sm" onClick={() => setParts([...parts, { name: p.display_name, timezone: p.timezone, user_id: p.id }])}>
                + {p.display_name}
              </Button>
            ))}
            <Button type="button" size="sm" onClick={() => setParts([...parts, { name: "", timezone: "Europe/London" }])}>
              + External participant
            </Button>
          </div>
        </div>
        {save.error && <p className="text-sm text-bad sm:col-span-2">{save.error.message}</p>}
        <div className="flex justify-end gap-2 sm:col-span-2">
          <Button type="button" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" variant="primary" busy={save.isPending}>
            Save meeting
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

function NotesTab() {
  const notes = useApi<NoteT[]>(["notes"], "/notes");
  const [f, setF] = useState({ title: "", body: "" });
  const create = useAction<Body<"NoteIn">>("POST", "/notes", { invalidate: [["notes"]], onSuccess: () => setF({ title: "", body: "" }) });
  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_380px]">
      <Card title="Notes">
        <ul className="flex flex-col gap-3 text-sm">
          {(notes.data ?? []).map((n) => (
            <li key={n.id} className="border-b border-line/50 pb-2">
              <p className="font-medium">{n.title}</p>
              <p className="whitespace-pre-wrap text-muted">{n.body}</p>
              <p className="text-[11px] text-muted">Updated {fmtTime(n.updated_at)}</p>
            </li>
          ))}
          {notes.data?.length === 0 && <li className="text-muted">No notes yet.</li>}
        </ul>
      </Card>
      {!isDemo && (
        <Card title="New note">
          <form
            className="flex flex-col gap-3"
            onSubmit={(e) => {
              e.preventDefault();
              create.mutate(f);
            }}
          >
            <TextField label="Title" value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} required />
            <Field label="Text" htmlFor="nb">
              <Textarea id="nb" rows={6} value={f.body} onChange={(e) => setF({ ...f, body: e.target.value })} />
            </Field>
            <Button type="submit" variant="primary" busy={create.isPending}>
              Save note
            </Button>
          </form>
        </Card>
      )}
    </div>
  );
}

function ActionsTab() {
  const items = useApi<Action[]>(["actions"], "/action-items");
  const meetings = useApi<Meeting[]>(["meetings"], "/meetings");
  const people = useApi<Person[]>(["people"], "/people");
  const [f, setF] = useState({ title: "", meeting_id: "", assignee_id: "" });
  const create = useAction<Body<"ActionIn">>("POST", "/action-items", { invalidate: [["actions"]], onSuccess: () => setF({ title: "", meeting_id: "", assignee_id: "" }) });
  const toggle = useAction<{ id: string; status: string }>("PATCH", (b) => `/action-items/${b.id}`, { invalidate: [["actions"]] });
  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_380px]">
      <Card title="Action items">
        <ul className="flex flex-col gap-1.5 text-sm">
          {(items.data ?? []).map((a) => (
            <li key={a.id} className="flex items-center justify-between gap-2">
              <label className="flex items-center gap-2">
                <input type="checkbox" checked={a.status === "done"} disabled={isDemo} onChange={() => toggle.mutate({ id: a.id, status: a.status === "done" ? "open" : "done" })} />
                <span className={a.status === "done" ? "line-through text-muted" : ""}>{a.title}</span>
              </label>
              <span className="text-xs text-muted">{a.assignee ?? "Unassigned"}</span>
            </li>
          ))}
          {items.data?.length === 0 && <li className="text-muted">No action items.</li>}
        </ul>
      </Card>
      {!isDemo && (
        <Card title="New action item">
          <form
            className="flex flex-col gap-3"
            onSubmit={(e) => {
              e.preventDefault();
              create.mutate({ title: f.title, meeting_id: f.meeting_id || null, assignee_id: f.assignee_id || null });
            }}
          >
            <TextField label="Title" value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} required />
            <Field label="Meeting" htmlFor="am">
              <Select id="am" value={f.meeting_id} onChange={(e) => setF({ ...f, meeting_id: e.target.value })}>
                <option value="">None</option>
                {(meetings.data ?? []).map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.title}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Assignee" htmlFor="aa">
              <Select id="aa" value={f.assignee_id} onChange={(e) => setF({ ...f, assignee_id: e.target.value })}>
                <option value="">Me</option>
                {(people.data ?? []).filter((p) => p.active).map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.display_name}
                  </option>
                ))}
              </Select>
            </Field>
            <Button type="submit" variant="primary" busy={create.isPending}>
              Add
            </Button>
          </form>
        </Card>
      )}
    </div>
  );
}
