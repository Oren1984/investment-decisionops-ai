import { Fragment, type ReactNode } from "react";
import { Link } from "react-router-dom";

/** Minimal, safe Markdown → React (no HTML injection): headings, paragraphs, lists, tables, code, bold, italics, links. */
function inline(text: string, keyBase: string): ReactNode[] {
  const out: ReactNode[] = [];
  const re = /(\*\*[^*]+\*\*|\*[^*\s][^*]*\*|`[^`]+`|\[[^\]]+\]\([^)]+\))/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let i = 0;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const tok = m[0];
    const key = `${keyBase}-${i++}`;
    if (tok.startsWith("**")) out.push(<strong key={key}>{tok.slice(2, -2)}</strong>);
    else if (tok.startsWith("*")) out.push(<em key={key}>{tok.slice(1, -1)}</em>);
    else if (tok.startsWith("`")) out.push(<code key={key}>{tok.slice(1, -1)}</code>);
    else {
      const lm = /\[([^\]]+)\]\(([^)]+)\)/.exec(tok)!;
      const href = lm[2];
      if (href.startsWith("/")) out.push(<Link key={key} to={href}>{lm[1]}</Link>);
      else if (/^https:\/\//.test(href)) out.push(<a key={key} href={href} target="_blank" rel="noreferrer noopener">{lm[1]}</a>);
      else out.push(lm[1]);
    }
    last = m.index + tok.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

const LIST = /^(\s*)(?:([-*])|(\d+)\.)\s+(.*)$/;
type ListLine = { indent: number; ordered: boolean; num: number; text: string };

/** Lists with nesting by indentation: deeper lines belong to the item above, and a numbered list keeps counting. */
function renderList(lines: ListLine[], key: string): ReactNode[] {
  const out: ReactNode[] = [];
  let i = 0;
  while (i < lines.length) {
    const { indent, ordered, num } = lines[i];
    const items: ReactNode[] = [];
    while (i < lines.length && lines[i].indent === indent && lines[i].ordered === ordered) {
      const item = lines[i++];
      const children: ListLine[] = [];
      while (i < lines.length && lines[i].indent > indent) children.push(lines[i++]);
      const itemKey = `${key}-${out.length}-${items.length}`;
      items.push(
        <li key={itemKey}>
          {inline(item.text, itemKey)}
          {children.length > 0 && renderList(children, itemKey)}
        </li>,
      );
    }
    const Tag = ordered ? "ol" : "ul";
    out.push(<Tag key={`${key}-${out.length}`} start={ordered && num !== 1 ? num : undefined}>{items}</Tag>);
  }
  return out;
}

export function Markdown({ source }: { source: string }) {
  const lines = source.replace(/\r/g, "").split("\n");
  const blocks: ReactNode[] = [];
  let i = 0;
  let k = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) {
      i++;
      continue;
    }
    const h = /^(#{1,3})\s+(.*)$/.exec(line);
    if (h) {
      const level = h[1].length;
      const content = inline(h[2], `h${k}`);
      blocks.push(level === 1 ? <h2 key={k++}>{content}</h2> : level === 2 ? <h3 key={k++}>{content}</h3> : <h4 key={k++} className="font-semibold">{content}</h4>);
      i++;
      continue;
    }
    if (line.startsWith("```")) {
      const code: string[] = [];
      i++;
      while (i < lines.length && !lines[i].startsWith("```")) code.push(lines[i++]);
      i++;
      blocks.push(
        <pre key={k++} tabIndex={0} className="my-2 overflow-x-auto rounded bg-surface-2 p-3 text-xs">
          <code>{code.join("\n")}</code>
        </pre>,
      );
      continue;
    }
    if (line.startsWith("|")) {
      const rows: string[][] = [];
      while (i < lines.length && lines[i].startsWith("|")) {
        const cells = lines[i].split("|").slice(1, -1).map((c) => c.trim());
        if (!cells.every((c) => /^:?-+:?$/.test(c))) rows.push(cells);
        i++;
      }
      const [head, ...body] = rows;
      blocks.push(
        <div key={k++} className="overflow-x-auto" tabIndex={0} role="region" aria-label="Table">
          <table>
            <thead>
              <tr>{head.map((c, j) => <th key={j}>{inline(c, `t${k}-${j}`)}</th>)}</tr>
            </thead>
            <tbody>
              {body.map((r, ri) => (
                <tr key={ri}>{r.map((c, j) => <td key={j}>{inline(c, `t${k}-${ri}-${j}`)}</td>)}</tr>
              ))}
            </tbody>
          </table>
        </div>,
      );
      continue;
    }
    if (LIST.test(line)) {
      const items: ListLine[] = [];
      while (i < lines.length && LIST.test(lines[i])) {
        const m = LIST.exec(lines[i++])!;
        items.push({ indent: m[1].length, ordered: m[3] !== undefined, num: Number(m[3] ?? 1), text: m[4] });
      }
      blocks.push(<Fragment key={k++}>{renderList(items, `l${k}`)}</Fragment>);
      continue;
    }
    const para: string[] = [];
    while (i < lines.length && lines[i].trim() && !/^(#{1,3}\s|```|\||\s*[-*]\s|\s*\d+\.\s)/.test(lines[i])) para.push(lines[i++]);
    blocks.push(<p key={k++}>{inline(para.join(" "), `p${k}`)}</p>);
  }
  return <div className="prose-help">{blocks.map((b, j) => <Fragment key={j}>{b}</Fragment>)}</div>;
}
