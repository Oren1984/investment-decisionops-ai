import * as DialogPrimitive from "@radix-ui/react-dialog";
import * as TabsPrimitive from "@radix-ui/react-tabs";
import { type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes, forwardRef, useId } from "react";
import { Link } from "react-router-dom";
import type { ApiError } from "../../api/client";
import type { OutputLabel } from "../../api/types";

export function cx(...parts: (string | false | null | undefined)[]) {
  return parts.filter(Boolean).join(" ");
}

type Variant = "primary" | "secondary" | "ghost" | "danger";
const VARIANTS: Record<Variant, string> = {
  primary: "bg-accent text-accent-fg hover:opacity-90 border border-transparent",
  secondary: "bg-surface-2 text-fg border border-line hover:border-accent/60",
  ghost: "bg-transparent text-fg border border-transparent hover:bg-surface-2",
  danger: "bg-bad text-white border border-transparent hover:opacity-90",
};

/** Button styling for elements that must stay links (e.g. external links), so no button is nested in a link. */
export function buttonClass(variant: Variant = "secondary", size: "sm" | "md" = "md", className?: string) {
  return cx(
    "inline-flex items-center justify-center gap-1.5 rounded-md font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed",
    size === "sm" ? "px-2.5 py-1 text-xs" : "px-3.5 py-2 text-sm",
    VARIANTS[variant],
    className,
  );
}

export const Button = forwardRef<HTMLButtonElement, ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: "sm" | "md"; busy?: boolean }>(
  function Button({ variant = "secondary", size = "md", busy, className, children, disabled, ...rest }, ref) {
    return (
      <button
        ref={ref}
        className={buttonClass(variant, size, className)}
        disabled={disabled || busy}
        aria-busy={busy || undefined}
        {...rest}
      >
        {busy && <Spinner small />}
        {children}
      </button>
    );
  },
);

export function Card({ title, actions, children, className, help, id }: { title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string; help?: string; id?: string }) {
  return (
    <section className={cx("rounded-lg border border-line bg-surface", className)} aria-labelledby={title && id ? `${id}-title` : undefined}>
      {(title || actions) && (
        <header className="flex items-center justify-between gap-2 border-b border-line px-4 py-2.5">
          <h2 id={id ? `${id}-title` : undefined} className="flex items-center gap-2 text-sm font-semibold">
            {title}
            {help && <HelpLink slug={help} />}
          </h2>
          {actions && <div className="flex items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}

export function PageHeader({ title, subtitle, actions, help }: { title: string; subtitle?: ReactNode; actions?: ReactNode; help?: string }) {
  return (
    <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="flex items-center gap-2 text-xl font-semibold tracking-tight">
          {title}
          {help && <HelpLink slug={help} />}
        </h1>
        {subtitle && <p className="mt-0.5 text-sm text-muted">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

const TONES = {
  neutral: "border-line text-muted",
  good: "border-good/40 text-good",
  warn: "border-warn/40 text-warn",
  bad: "border-bad/40 text-bad",
  accent: "border-accent/40 text-accent",
  model: "border-model/40 text-model",
  computed: "border-computed/40 text-computed",
  simulated: "border-simulated/40 text-simulated",
} as const;
export type Tone = keyof typeof TONES;

export function Badge({ tone = "neutral", children, title, className }: { tone?: Tone; children: ReactNode; title?: string; className?: string }) {
  return (
    <span title={title} className={cx("inline-flex items-center gap-1 whitespace-nowrap rounded border px-1.5 py-0.5 text-[11px] font-medium uppercase tracking-wide", TONES[tone], className)}>
      {children}
    </span>
  );
}

const LABEL_TEXT: Record<OutputLabel, string> = { simulated: "Simulated", computed: "Computed", model: "Model-generated", user: "Entered by you" };
const LABEL_HELP: Record<OutputLabel, string> = {
  simulated: "Template or fixture output from the no-model baseline. Not analysis by a language model.",
  computed: "Produced by deterministic code (retrieval, calculations, checks).",
  model: "Written by the local language model. Verify against the cited sources.",
  user: "Text you entered.",
};
export function OutputBadge({ label, detail }: { label: OutputLabel | null | undefined; detail?: string }) {
  if (!label) return null;
  const tone: Tone = label === "model" ? "model" : label === "computed" ? "computed" : label === "simulated" ? "simulated" : "neutral";
  return (
    <Badge tone={tone} title={LABEL_HELP[label]}>
      {LABEL_TEXT[label]}
      {detail ? <span className="normal-case tracking-normal opacity-80">· {detail}</span> : null}
    </Badge>
  );
}

export function Spinner({ small }: { small?: boolean }) {
  return (
    <span role="status" aria-label="Loading" className={cx("inline-block animate-spin rounded-full border-2 border-current border-t-transparent", small ? "h-3 w-3" : "h-5 w-5")} />
  );
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 py-6 text-sm text-muted">
      <Spinner small /> {label}
    </div>
  );
}

export function EmptyState({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-start gap-2 rounded-md border border-dashed border-line px-4 py-6">
      <p className="text-sm font-medium">{title}</p>
      {children && <div className="text-sm text-muted">{children}</div>}
      {action}
    </div>
  );
}

export function ErrorState({ error, retry }: { error: ApiError | Error | null | undefined; retry?: () => void }) {
  if (!error) return null;
  const e = error as ApiError;
  return (
    <div role="alert" className="flex flex-col gap-2 rounded-md border border-bad/40 bg-bad/5 px-4 py-3 text-sm">
      <p className="font-medium text-bad">{e.message}</p>
      <div className="flex flex-wrap items-center gap-3">
        {retry && (
          <Button size="sm" onClick={retry}>
            Try again
          </Button>
        )}
        {e.helpSlug && <HelpLink slug={e.helpSlug} label="How to fix this" />}
      </div>
    </div>
  );
}

export function Notice({ tone = "neutral", children, title }: { tone?: "neutral" | "warn" | "good" | "bad" | "accent"; children: ReactNode; title?: string }) {
  const cls = {
    neutral: "border-line bg-surface-2",
    warn: "border-warn/40 bg-warn/5",
    good: "border-good/40 bg-good/5",
    bad: "border-bad/40 bg-bad/5",
    accent: "border-accent/40 bg-accent/5",
  }[tone];
  return (
    <div className={cx("rounded-md border px-3 py-2 text-sm", cls)} role={tone === "bad" || tone === "warn" ? "alert" : undefined}>
      {title && <p className="font-medium">{title}</p>}
      <div className={title ? "mt-0.5 text-muted" : ""}>{children}</div>
    </div>
  );
}

export function HelpLink({ slug, label }: { slug: string; label?: string }) {
  return (
    <Link to={`/help/${slug}`} className="inline-flex items-center gap-1 text-xs font-normal text-accent hover:underline" aria-label={label ?? "Help for this section"}>
      <span aria-hidden className="inline-flex h-4 w-4 items-center justify-center rounded-full border border-accent/60 text-[10px]">?</span>
      {label}
    </Link>
  );
}

export function Field({ label, hint, error, children, htmlFor }: { label: string; hint?: ReactNode; error?: string; children: ReactNode; htmlFor?: string }) {
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={htmlFor} className="text-xs font-medium text-muted">
        {label}
      </label>
      {children}
      {hint && !error && <p className="text-xs text-muted">{hint}</p>}
      {error && (
        <p className="text-xs text-bad" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

const inputCls = "w-full rounded-md border border-line bg-surface-2 px-2.5 py-1.5 text-sm text-fg placeholder:text-muted/70 focus:border-accent";
export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function Input({ className, ...rest }, ref) {
  return <input ref={ref} className={cx(inputCls, className)} {...rest} />;
});
export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(function Textarea({ className, ...rest }, ref) {
  return <textarea ref={ref} className={cx(inputCls, "min-h-20", className)} {...rest} />;
});
export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(function Select({ className, children, ...rest }, ref) {
  return (
    <select ref={ref} className={cx(inputCls, className)} {...rest}>
      {children}
    </select>
  );
});

export function TextField(props: InputHTMLAttributes<HTMLInputElement> & { label: string; hint?: ReactNode; error?: string }) {
  const id = useId();
  const { label, hint, error, ...rest } = props;
  return (
    <Field label={label} hint={hint} error={error} htmlFor={id}>
      <Input id={id} aria-invalid={error ? true : undefined} {...rest} />
    </Field>
  );
}

export function Dialog({ open, onOpenChange, title, description, children, wide }: { open: boolean; onOpenChange: (o: boolean) => void; title: string; description?: ReactNode; children: ReactNode; wide?: boolean }) {
  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-40 bg-black/60" />
        <DialogPrimitive.Content
          className={cx(
            "fixed left-1/2 top-1/2 z-50 max-h-[90vh] w-[calc(100vw-2rem)] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-lg border border-line bg-surface p-5 shadow-xl",
            wide ? "max-w-2xl" : "max-w-md",
          )}
        >
          <DialogPrimitive.Title className="text-base font-semibold">{title}</DialogPrimitive.Title>
          {description ? (
            <DialogPrimitive.Description className="mt-1 text-sm text-muted">{description}</DialogPrimitive.Description>
          ) : (
            <DialogPrimitive.Description className="sr-only">{title}</DialogPrimitive.Description>
          )}
          <div className="mt-4">{children}</div>
          <DialogPrimitive.Close className="absolute right-3 top-3 rounded px-2 text-muted hover:text-fg" aria-label="Close">
            ✕
          </DialogPrimitive.Close>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}

export function Tabs({ tabs, value, onValueChange, defaultValue }: { tabs: { value: string; label: ReactNode; content: ReactNode }[]; value?: string; onValueChange?: (v: string) => void; defaultValue?: string }) {
  return (
    <TabsPrimitive.Root value={value} onValueChange={onValueChange} defaultValue={defaultValue ?? tabs[0]?.value}>
      <TabsPrimitive.List className="mb-4 flex gap-1 overflow-x-auto border-b border-line" aria-label="Sections">
        {tabs.map((t) => (
          <TabsPrimitive.Trigger
            key={t.value}
            value={t.value}
            className="whitespace-nowrap border-b-2 border-transparent px-3 py-2 text-sm text-muted hover:text-fg data-[state=active]:border-accent data-[state=active]:text-fg"
          >
            {t.label}
          </TabsPrimitive.Trigger>
        ))}
      </TabsPrimitive.List>
      {tabs.map((t) => (
        <TabsPrimitive.Content key={t.value} value={t.value}>
          {t.content}
        </TabsPrimitive.Content>
      ))}
    </TabsPrimitive.Root>
  );
}

export function Stat({ label, value, sub, tone }: { label: string; value: ReactNode; sub?: ReactNode; tone?: "good" | "bad" | "warn" }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-xs text-muted">{label}</span>
      <span className={cx("num text-lg font-semibold", tone === "good" && "text-good", tone === "bad" && "text-bad", tone === "warn" && "text-warn")}>{value}</span>
      {sub && <span className="text-xs text-muted">{sub}</span>}
    </div>
  );
}

export function Table({ children, caption }: { children: ReactNode; caption?: string }) {
  return (
    <div className="-mx-4 overflow-x-auto px-4" tabIndex={0} role="region" aria-label={caption ?? "Table"}>
      <table className="w-full min-w-[560px] border-collapse text-sm">
        {caption && <caption className="sr-only">{caption}</caption>}
        {children}
      </table>
    </div>
  );
}
export const Th = ({ children, right }: { children?: ReactNode; right?: boolean }) => (
  <th scope="col" className={cx("border-b border-line px-2 py-1.5 text-xs font-medium text-muted", right ? "text-right" : "text-left")}>
    {children}
  </th>
);
export const Td = ({ children, right, className }: { children?: ReactNode; right?: boolean; className?: string }) => (
  <td className={cx("border-b border-line/60 px-2 py-1.5 align-top", right && "num text-right", className)}>{children}</td>
);

export function KeyValue({ items }: { items: [ReactNode, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-[minmax(110px,auto)_1fr] gap-x-4 gap-y-1.5 text-sm">
      {items.map(([k, v], i) => (
        <div key={i} className="contents">
          <dt className="text-muted">{k}</dt>
          <dd className="min-w-0 break-words">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

export function statusTone(status: string): Tone {
  if (["filled", "succeeded", "ready_for_decision", "decided", "closed", "fresh", "connected", "approved", "verified", "scheduled", "linked", "active", "done"].includes(status)) return "good";
  if (["rejected", "failed", "blocked", "cancel_rejected", "not_found", "error", "invalidated", "expired", "disconnected", "redacted"].includes(status)) return "bad";
  if (["uncertain", "reconciling", "stale", "interrupted", "cancel_requested", "partially_filled", "pending_approval", "unavailable", "not_configured", "simulated"].includes(status)) return "warn";
  if (["running", "queued", "submitting", "acknowledged", "researching", "analyzing", "scenarios", "quality_review", "scoped"].includes(status)) return "accent";
  return "neutral";
}

export function StatusBadge({ status, label }: { status: string; label?: string }) {
  return <Badge tone={statusTone(status)}>{label ?? status.replace(/_/g, " ")}</Badge>;
}
