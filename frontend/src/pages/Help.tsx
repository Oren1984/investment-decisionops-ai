import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import type { HelpArticleSummary } from "../api/types";
import { Card, ErrorState, Input, Loading, PageHeader, cx } from "../components/ui";
import { useApi } from "../hooks/useApi";
import { Markdown } from "../lib/markdown";

/** Topic groups in reading order. Article front matter `category` maps here; unknown categories follow at the end. */
const TOPICS: { category: string; label: string; description: string }[] = [
  { category: "Start", label: "Getting started", description: "What the app does and its Mock, Paper and Live modes." },
  { category: "Setup", label: "Setup and account", description: "First run, account recovery, the local model and IBKR Paper." },
  { category: "Decisions", label: "Decisions and research", description: "Agents and tools, the evidence checklist, replay and reviews." },
  { category: "Markets", label: "Markets", description: "Venues, trading sessions and calendars." },
  { category: "Portfolio", label: "Portfolio", description: "Holdings and exposure." },
  { category: "Library", label: "Knowledge library", description: "Documents, citations and deletion." },
  { category: "Orders", label: "Orders and approvals", description: "Approvals, the Stop control and reconciliation." },
  { category: "Collaboration", label: "Collaboration and meetings", description: "Sharing and Zoom, Google Meet, Teams or other meeting links." },
  { category: "Settings", label: "Settings and security", description: "Integration status labels, security, privacy and your data." },
  { category: "Operations", label: "Operations", description: "Health, backups, governance and troubleshooting." },
  { category: "Alerts", label: "Alerts", description: "What each alert means and what to do." },
];

/** Readable names for the screens an article points to. */
const SCREENS: Record<string, string> = {
  "/": "Overview", "/markets": "Markets", "/portfolio": "Portfolio", "/decisions": "Decisions", "/decisions/new": "New decision",
  "/orders": "Orders", "/collaboration": "Collaboration", "/library": "Library", "/settings": "Settings", "/help": "Help Center", "/shared": "Shared with me",
};

type Group = { category: string; label: string; description: string; items: HelpArticleSummary[] };

function groupArticles(articles: HelpArticleSummary[]): Group[] {
  const byCategory = new Map<string, HelpArticleSummary[]>();
  for (const a of articles) byCategory.set(a.category, [...(byCategory.get(a.category) ?? []), a]);
  const known = TOPICS.filter((t) => byCategory.has(t.category)).map((t) => ({ ...t, items: byCategory.get(t.category)! }));
  const other = [...byCategory.keys()].filter((c) => !TOPICS.some((t) => t.category === c))
    .map((c) => ({ category: c, label: c, description: "", items: byCategory.get(c)! }));
  return [...known, ...other];
}

/** Inside a group the category already says "Alert", so the list drops the repeated prefix. */
const shortTitle = (a: HelpArticleSummary) => {
  const t = a.title.replace(/^Alert:\s*/i, "");
  return t.charAt(0).toUpperCase() + t.slice(1);
};

export default function Help() {
  const { slug } = useParams();
  const [q, setQ] = useState("");
  const list = useApi<HelpArticleSummary[]>(["help"], "/help", { staleTime: Infinity });
  const results = useApi<HelpArticleSummary[]>(["help-search", q], q.length >= 2 ? `/help/search?q=${encodeURIComponent(q)}` : null);
  const article = useApi<HelpArticleSummary & { body: string }>(["help-article", slug], slug ? `/help/${slug}` : null);
  const groups = groupArticles(list.data ?? []);
  const current = groups.find((g) => g.items.some((a) => a.slug === slug));
  const navRef = useRef<HTMLElement>(null);
  // Keep the selected article visible in the (independently scrolling) topic list.
  useEffect(() => {
    const nav = navRef.current;
    const selected = nav?.querySelector<HTMLElement>('a[aria-current="page"]');
    if (nav && selected && (selected.offsetTop < nav.scrollTop || selected.offsetTop > nav.scrollTop + nav.clientHeight - 40)) {
      nav.scrollTop = selected.offsetTop - nav.clientHeight / 3;
    }
  }, [slug, list.data]);

  return (
    <>
      <PageHeader title="Help Center" subtitle="Short, task-oriented guides. Every “?” in the app opens the article for that screen." />
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-[280px_1fr]">
        {/* On small screens an open article takes the full width; "All topics" brings the list back. */}
        <nav ref={navRef} aria-label="Help articles" className={cx("relative flex-col gap-4 lg:sticky lg:top-32 lg:flex lg:max-h-[calc(100vh-9rem)] lg:self-start lg:overflow-y-auto lg:pr-1", slug ? "hidden" : "flex")}>
          <Input type="search" aria-label="Search help" placeholder="Search help…" value={q} onChange={(e) => setQ(e.target.value)} />
          {q.length >= 2 ? (
            <section aria-label="Search results">
              <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">Search results</p>
              <ul className="flex flex-col gap-1">
                {(results.data ?? []).map((r) => (
                  <li key={r.slug}>
                    <Link to={`/help/${r.slug}`} className="block rounded-md px-3 py-2 hover:bg-surface-2" onClick={() => setQ("")}>
                      <span className="text-sm font-medium text-accent">{r.title}</span>
                      {r.snippet && <span className="mt-0.5 block text-xs text-muted">{r.snippet.replace(/[«»]/g, "")}</span>}
                    </Link>
                  </li>
                ))}
                {results.data?.length === 0 && <li className="px-3 py-2 text-sm text-muted">No matching articles.</li>}
              </ul>
            </section>
          ) : (
            groups.map((g) => (
              <section key={g.category} aria-labelledby={`help-group-${g.category}`}>
                <h2 id={`help-group-${g.category}`} className="mb-1 px-3 text-xs font-semibold uppercase tracking-wide text-muted">
                  {g.label}
                </h2>
                <ul className="flex flex-col gap-0.5">
                  {g.items.map((a) => {
                    const selected = a.slug === slug;
                    return (
                      <li key={a.slug}>
                        <Link
                          to={`/help/${a.slug}`}
                          aria-current={selected ? "page" : undefined}
                          className={cx(
                            "block rounded-md border-l-2 px-3 py-1.5 text-sm leading-snug",
                            selected ? "border-accent bg-surface-2 font-medium text-fg" : "border-transparent text-muted hover:bg-surface-2 hover:text-fg",
                          )}
                        >
                          {shortTitle(a)}
                        </Link>
                      </li>
                    );
                  })}
                </ul>
              </section>
            ))
          )}
          <ErrorState error={list.error} retry={() => list.refetch()} />
        </nav>

        <div className="min-w-0">
          {!slug && <TopicOverview groups={groups} loading={list.isLoading} />}
          {slug && (
            <Card className="p-5 md:p-7">
              <nav aria-label="Breadcrumb" className="mb-4 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted">
                <Link to="/help" className="text-accent hover:underline">
                  <span aria-hidden className="lg:hidden">← </span>
                  <span className="lg:hidden">All topics</span>
                  <span className="hidden lg:inline">Help Center</span>
                </Link>
                {current && (
                  <>
                    <span aria-hidden>›</span>
                    <span>{current.label}</span>
                  </>
                )}
              </nav>
              {article.isLoading && <Loading />}
              <ErrorState error={article.error} />
              {article.data && (
                <article className="max-w-3xl">
                  <h1 className="text-2xl font-semibold tracking-tight">{article.data.title}</h1>
                  {article.data.summary && <p className="mt-2 text-base text-muted">{article.data.summary}</p>}
                  <div className="mt-6 border-t border-line pt-5">
                    <Markdown source={article.data.body} />
                  </div>
                  {(article.data.routes ?? []).length > 0 && (
                    <div className="mt-8 rounded-md border border-line bg-surface-2 px-4 py-3 text-sm">
                      <span className="mr-2 font-medium">Related screens:</span>
                      {article.data.routes!.map((r) => (
                        <Link key={r} to={r} className="mr-3 inline-block text-accent hover:underline">
                          {SCREENS[r] ?? r} →
                        </Link>
                      ))}
                    </div>
                  )}
                </article>
              )}
            </Card>
          )}
        </div>
      </div>
    </>
  );
}

function TopicOverview({ groups, loading }: { groups: Group[]; loading: boolean }) {
  if (loading) return <Loading />;
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 2xl:grid-cols-3">
      {groups.map((g) => (
        <section key={g.category} className="flex flex-col rounded-lg border border-line bg-surface p-4" aria-labelledby={`help-topic-${g.category}`}>
          <h2 id={`help-topic-${g.category}`} className="text-base font-semibold">
            {g.label}
          </h2>
          {g.description && <p className="mt-1 text-sm text-muted">{g.description}</p>}
          <ul className="mt-3 flex flex-col gap-1.5 border-t border-line pt-3 text-sm">
            {g.items.map((a) => (
              <li key={a.slug}>
                <Link to={`/help/${a.slug}`} className="text-accent hover:underline">
                  {shortTitle(a)}
                </Link>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}
