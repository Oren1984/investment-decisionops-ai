/** Response shapes used by the UI (request bodies are validated server-side by Pydantic). */

export type Role = "owner" | "collaborator" | "demo";
export type OutputLabel = "simulated" | "computed" | "model" | "user";

export interface Me {
  id: string;
  email: string;
  display_name: string;
  role: Role;
  timezone: string;
  totp_enabled: boolean;
  stepped_up_until: string | null;
}

export interface AuthStatus {
  profile: "owner" | "demo" | "test";
  setup_required: boolean;
  authenticated: boolean;
  user: Me | null;
}

export interface Venue {
  mic: string;
  name: string;
  short: string;
  country: string;
  timezone: string;
  currency: string;
  calendar: string;
  has_lunch_break: boolean;
  execution_scope: string;
  execution_status: string;
}

export interface SessionTime { utc: string; local: string }
export interface VenueState {
  mic: string;
  timezone: string;
  local_time: string;
  utc_offset_minutes: number;
  state: "open" | "closed" | "break";
  reason: string | null;
  next_event: { kind: string; at: string; seconds: number } | null;
  today: { date: string; open: SessionTime; close: SessionTime; break_start: SessionTime | null; break_end: SessionTime | null; early_close: boolean } | null;
  next_open: string | null;
  home_timezone: string;
  date_difference_days: number;
  venue: { mic: string; name: string; short: string; currency: string };
}

export interface Quote {
  instrument_id: string;
  symbol: string;
  price: number | null;
  change_pct?: number;
  currency?: string;
  as_of: string | null;
  age_seconds: number | null;
  freshness: "fresh" | "stale" | "missing";
  label: string;
}

export interface Instrument {
  id: string;
  symbol: string;
  name: string;
  venue_mic: string;
  currency: string;
  kind: string;
  asset_class: string;
  tradable: boolean;
  not_tradable_reason: string | null;
  quote?: Quote;
}

export interface Feed {
  key: string;
  name: string;
  source_label: string;
  state: "not_configured" | "fresh" | "stale" | "error";
  last_success_at: string | null;
  last_error: string | null;
  stale_since: string | null;
  meta: Record<string, unknown>;
}

export interface PortfolioRow {
  kind: "position" | "cash" | "manual";
  id?: string;
  instrument_id?: string;
  symbol: string;
  name: string;
  venue_mic: string | null;
  asset_class: string;
  currency: string;
  quantity?: number;
  avg_cost?: number;
  price?: number;
  unit_value?: number;
  value_local: number;
  value_home: number;
  weight_pct: number;
  unrealized_pct?: number | null;
  value_as_of?: string;
  notes?: string | null;
  source: string;
  quote?: Quote;
}

export interface ExposureGroup { key: string; value_home: number; pct: number }
export interface Portfolio {
  mode: string;
  home_currency: string;
  label: string;
  as_of: string;
  fx_as_of: string | null;
  total_home: number;
  positions: PortfolioRow[];
  manual_holdings: PortfolioRow[];
  exposure: { asset_class: ExposureGroup[]; currency: ExposureGroup[]; venue: ExposureGroup[] };
  available: boolean;
}

export interface WorkflowBarData {
  decision_id: string;
  title: string;
  status: string;
  status_label: string;
  stages: { key: string; label: string; state: "done" | "current" | "todo" }[];
  blockers: string[];
  next_action: string;
  run: { id: string; status: string; mode: string; current_step: string | null } | null;
}

export interface DecisionSummary {
  id: string;
  title: string;
  question: string;
  status: string;
  status_label: string;
  mode: string;
  outcome: string | null;
  current_version: number;
  created_at: string;
  updated_at: string;
  decided_at: string | null;
  instrument_ids: string[];
  blocked_reason: string | null;
  checks: { passed: number; total: number } | null;
  integrity_status: string | null;
  run_id?: string | null;
}

export interface Proposal { id: string; kind: string; payload: Record<string, unknown>; rationale: string; output_label: OutputLabel; status: string; created_at: string }
export interface Review {
  id: string; created_at: string; process_rubric: Record<string, number>; process_score: number; process_max: number;
  outcome_return_pct: number | null; benchmark_return_pct: number | null;
  assumption_observations: { assumption_code: string; observation: string; held: boolean | null }[];
  notes: string | null; quadrant: { process_good: boolean; outcome_good: boolean | null };
}

export interface DecisionDetail extends DecisionSummary {
  workflow: WorkflowBarData;
  snapshot: { id: string; hash: string; integrity_status: string; checks_passed: number; checks_total: number; created_at: string } | null;
  versions: { version_no: number; kind: string; outcome: string; rationale: string; explanation: string | null; snapshot_id: string | null; created_at: string }[];
  events: { at: string; kind: string; summary: string }[];
  assumptions: { code: string; text: string; metric: string | null; expected: string | null }[];
  proposals: Proposal[];
  reviews: Review[];
  lessons: { id: string; text: string; tags: string[] }[];
  orders: { id: string; status: string; side: string; quantity: number; mode: string }[];
  rubric: Record<string, string>;
}

export interface EvidenceItem {
  id: string;
  ordinal: number;
  kind: string;
  title: string;
  content: Record<string, any> | null; // eslint-disable-line @typescript-eslint/no-explicit-any
  provenance: Record<string, any> | null; // eslint-disable-line @typescript-eslint/no-explicit-any
  output_label: OutputLabel;
  item_hash: string;
  source_removed_at: string | null;
  redacted_at: string | null;
  redaction_reason: string | null;
}

export interface Snapshot {
  snapshot_id: string;
  created_at: string;
  snapshot_hash: string;
  integrity_status: "verified" | "redacted";
  checks_passed: number;
  checks_total: number;
  verification: { snapshot_hash_ok: boolean; items_verified: number; items_failed: number; items_redacted: number; ok: boolean };
  banner: string | null;
  items: EvidenceItem[];
}

export interface RunStep {
  id: string; step: string; label: string; attempt: number; status: string; output_kind: OutputLabel | null;
  output: Record<string, any> | null; notes: string[]; started_at: string; finished_at: string | null; // eslint-disable-line @typescript-eslint/no-explicit-any
  duration_ms: number | null; model_name: string | null; model_digest: string | null; prompt_version: string | null;
  tokens_in: number | null; tokens_out: number | null; tool_calls: number; error: string | null; redacted: boolean;
}

export interface Run {
  id: string; decision_id: string; mode: string; status: string; current_step: string | null; cancel_requested: boolean;
  created_at: string; started_at: string | null; finished_at: string | null; deadline_at: string | null; error: string | null;
  model_name: string | null; model_digest: string | null; resume_count: number; correlation_id: string | null;
  steps?: RunStep[]; tool_calls?: Record<string, { ok: number; failed: number }>;
}

export interface LimitCheck { key: string; name: string; passed: boolean; detail: string }
export interface OrderPreview {
  mode: string; broker: string; account_id: string;
  instrument: { symbol: string; name: string; broker_instrument_id: string | null; venue_mic: string };
  currency: string; side: string; quantity: number; order_type: string; limit_price: number | null; stop_price: number | null; tif: string;
  estimated_commission: { amount: number | null; currency: string | null; label: string; detail: string | null; unknown: boolean };
  notional: { amount: number; currency: string; home_amount: number; home_currency: string; fx_rate: number; fx_as_of: string | null; reference_price: number };
  quote: Quote; session: { state: string; reason: string | null; next_event: VenueState["next_event"] };
  limit_checks: LimitCheck[]; all_checks_passed: boolean; linked_decision: { id: string; title: string } | null;
  client_order_id: string; payload_hash: string; label: string; mock_scenario: string | null;
}

export interface Order {
  id: string; mode: string; broker: string; account_id: string; decision_id: string | null;
  instrument: { id: string; symbol: string; name: string; venue_mic: string; currency: string };
  side: string; quantity: number; order_type: string; limit_price: number | null; stop_price: number | null; tif: string;
  client_order_id: string; status: string; broker_order_id: string | null; filled_quantity: number; avg_fill_price: number | null;
  mock_scenario: string | null; preview: OrderPreview | null; previewed_at: string | null; submitted_at: string | null;
  last_error: string | null; created_at: string; updated_at: string;
  approval: { status: string; expires_at: string; payload_hash: string; approved_at: string } | null;
  events?: { at: string; from: string | null; to: string; message: string; details: Record<string, unknown> }[];
  executions?: { exec_id: string; quantity: number; price: number; commission: number | null; at: string }[];
  duplicate?: boolean; note?: string | null;
}

export interface BrokerInfo {
  mode: string;
  connection: { status: string; account_id?: string | null; detail: string };
  capabilities: Record<string, unknown>;
  scenarios: Record<string, string>;
  stop: { engaged: boolean; changed_at: string | null; reason: string | null };
  live: { enabled: boolean; authorized: boolean; message: string };
  approval_expiry_minutes: number;
}

export interface LibraryDoc {
  id: string; title: string; filename: string; file_type: string; size_bytes: number; pages: number | null;
  status: string; error: string | null; chunk_count: number; embedding_model: string | null; created_at: string; indexed_at: string | null;
}

export interface AnswerStatement { text: string; kind: "quote" | "interpretation"; citations: string[]; flags: string[] }
export interface Answer {
  question: string; mode: "extractive" | "generated" | "abstained"; label: string;
  model: { model: string; tokens_in: number | null; tokens_out: number | null; duration_ms: number } | null;
  answer: string | null; statements: AnswerStatement[];
  citations: Record<string, { document_id: string; document_title: string; location: string; page: number | null; section: string | null }>;
  checks: { key: string; name: string; passed: boolean; detail: string; heuristic: boolean }[];
  disclaimer: string;
  retrieval: { method: string; embeddings: string; hits: { chunk_id: string; document_title: string; location: string; text: string; coverage: number; score: number }[]; model_error?: string };
}

export interface Meeting {
  id: string; title: string; starts_at: string; duration_minutes: number; ends_at: string; timezone: string;
  provider: "mock" | "manual" | "zoom"; provider_status: string; provider_error: string | null; join_url: string | null;
  link_provider: "zoom" | "google_meet" | "teams" | "other" | null; link_provider_label: string | null;
  agenda: string; decision_id: string | null;
  owner_time: TimeView; viewer_time: TimeView;
  participants: { id: string; name: string; user_id: string | null; time: TimeView }[];
  simulated: boolean; provider_note: string; recording: string;
}
export interface TimeView { timezone: string; local: string; label: string; utc_offset: string; day_shift: number }

export interface Integration { key: string; name: string; status: string; detail: string }
export interface HelpArticleSummary { slug: string; title: string; summary: string; category: string; routes?: string[]; snippet?: string }
