import { Bar, BarChart, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { ExposureGroup } from "../../api/types";
import { fmtMoney } from "../../lib/format";

const COLORS = ["var(--app-accent)", "var(--app-computed)", "var(--app-model)", "var(--app-good)", "var(--app-warn)", "var(--app-simulated)"];

/** Horizontal exposure bars with a text alternative table for screen readers. */
export function ExposureChart({ data, currency, title }: { data: ExposureGroup[]; currency: string; title: string }) {
  const rows = data.slice(0, 8);
  return (
    <figure>
      <div aria-hidden className="h-44">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart accessibilityLayer={false} data={rows} layout="vertical" margin={{ left: 8, right: 16, top: 4, bottom: 4 }}>
            <XAxis type="number" hide domain={[0, "dataMax"]} />
            <YAxis type="category" dataKey="key" width={64} tick={{ fill: "var(--app-muted)", fontSize: 11 }} axisLine={false} tickLine={false} />
            <Tooltip
              cursor={{ fill: "var(--app-surface-2)" }}
              contentStyle={{ background: "var(--app-surface)", border: "1px solid var(--app-line)", color: "var(--app-fg)", fontSize: 12 }}
              formatter={(v) => [`${Number(v).toFixed(1)}%`, "Share"]}
            />
            <Bar dataKey="pct" radius={[0, 3, 3, 0]} isAnimationActive={false}>
              {rows.map((_, i) => (
                <Cell key={i} fill={COLORS[i % COLORS.length]} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <table className="sr-only">
        <caption>{title}</caption>
        <tbody>
          {rows.map((r) => (
            <tr key={r.key}>
              <th>{r.key}</th>
              <td>{r.pct}%</td>
              <td>{fmtMoney(r.value_home, currency)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <figcaption className="mt-1 text-[11px] text-muted">{title} (share of total value, Computed)</figcaption>
    </figure>
  );
}
