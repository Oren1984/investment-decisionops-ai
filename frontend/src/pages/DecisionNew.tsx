import { type Resolver, useForm } from "react-hook-form";
import { useNavigate } from "react-router-dom";
import { z } from "zod";
import { post } from "../api/client";
import type { DecisionSummary, Instrument } from "../api/types";
import { Button, Card, ErrorState, Field, HelpLink, Notice, PageHeader, Textarea, TextField } from "../components/ui";
import { useApi } from "../hooks/useApi";
import { useMutation } from "@tanstack/react-query";
import type { ApiError } from "../api/client";

const schema = z.object({
  title: z.string().min(3, "At least 3 characters").max(200),
  question: z.string().min(10, "Describe the question in at least 10 characters").max(4000),
  instrument_ids: z.preprocess((v) => (Array.isArray(v) ? v : v ? [v] : []), z.array(z.string())),
  mode: z.enum(["deterministic", "model"]),
});
type FormValues = z.infer<typeof schema>;

/** Minimal Zod → react-hook-form resolver (avoids an extra dependency). */
const resolver: Resolver<FormValues> = async (values) => {
  const r = schema.safeParse(values);
  if (r.success) return { values: r.data, errors: {} };
  const errors: Record<string, { type: string; message: string }> = {};
  for (const issue of r.error.issues) errors[String(issue.path[0])] ??= { type: issue.code, message: issue.message };
  return { values: {}, errors } as never;
};

export default function DecisionNew() {
  const navigate = useNavigate();
  const instruments = useApi<Instrument[]>(["instruments"], "/markets/instruments");
  const agents = useApi<{ modes: { model: boolean }; model: { reason?: string; model: string } }>(["agents"], "/agents/status");
  const { register, handleSubmit, formState, watch } = useForm<FormValues>({
    resolver,
    defaultValues: { title: "", question: "", instrument_ids: [], mode: "deterministic" },
  });
  const create = useMutation<DecisionSummary, ApiError, FormValues>({
    mutationFn: (v) => post<DecisionSummary>("/decisions", { ...v, start_run: true }),
    onSuccess: (d) => navigate(`/decisions/${d.id}`),
  });
  const modelReady = agents.data?.modes.model ?? false;
  const selected = watch("instrument_ids");

  return (
    <>
      <PageHeader title="New question" subtitle="The workflow scopes the question, researches, analyses your portfolio, runs scenarios and reviews quality. You decide." help="decisions-and-replay" />
      <form onSubmit={handleSubmit((v) => create.mutate(v))} className="grid grid-cols-1 max-w-4xl gap-4">
        <Card>
          <div className="grid grid-cols-1 gap-3">
            <TextField label="Short title" placeholder="e.g. Add to NVDA after earnings?" {...register("title")} error={formState.errors.title?.message} />
            <Field label="Question" htmlFor="q" error={formState.errors.question?.message} hint="Mention the instrument(s) and what you are considering (buy, trim, hold).">
              <Textarea id="q" rows={4} {...register("question")} />
            </Field>
            <fieldset>
              <legend className="mb-1 text-xs font-medium text-muted">Instruments (optional — symbols in the question are detected too)</legend>
              <div className="flex max-h-40 flex-wrap gap-1.5 overflow-y-auto">
                {(instruments.data ?? []).map((i) => (
                  <label key={i.id} className={`cursor-pointer rounded border px-2 py-1 text-xs ${selected.includes(i.id) ? "border-accent bg-accent/10" : "border-line"}`}>
                    <input type="checkbox" value={i.id} className="sr-only" {...register("instrument_ids")} />
                    {i.symbol} <span className="text-muted">{i.venue_mic}</span>
                  </label>
                ))}
              </div>
            </fieldset>
            <fieldset className="flex flex-col gap-2">
              <legend className="mb-1 text-xs font-medium text-muted">
                Run mode <HelpLink slug="agents-and-labels" />
              </legend>
              <label className="flex items-start gap-2 text-sm">
                <input type="radio" value="deterministic" {...register("mode")} />
                <span>
                  Deterministic (always available) — computed analysis and clearly labelled <em>simulated</em> summaries. No language model.
                </span>
              </label>
              <label className={`flex items-start gap-2 text-sm ${modelReady ? "" : "opacity-60"}`}>
                <input type="radio" value="model" disabled={!modelReady} {...register("mode")} />
                <span>
                  Model-enabled — CrewAI agents on the local model ({agents.data?.model.model ?? "…"}). Numbers stay computed.
                  {!modelReady && <span className="block text-xs text-muted">Not available: {agents.data?.model.reason ?? "checking…"}</span>}
                </span>
              </label>
            </fieldset>
          </div>
        </Card>
        <Notice>Agents can only read and compute. They may suggest actions, but cannot place orders, share data or change settings.</Notice>
        <ErrorState error={create.error} />
        <div>
          <Button type="submit" variant="primary" busy={create.isPending}>
            Create and start research
          </Button>
        </div>
      </form>
    </>
  );
}
