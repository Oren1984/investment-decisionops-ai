import { CandlestickSeries, ColorType, createChart, type IChartApi } from "lightweight-charts";
import { useEffect, useRef } from "react";
import { useUi } from "../../store/ui";

type Bar = { time: string; open: number; high: number; low: number; close: number };

function cssVar(name: string) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

/** Financial chart (TradingView Lightweight Charts, Apache-2.0 — attribution and link required). */
export function PriceChart({ bars, symbol, label, height = 280 }: { bars: Bar[]; symbol: string; label: string; height?: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const theme = useUi((s) => s.theme);

  useEffect(() => {
    if (!ref.current) return;
    const chart = createChart(ref.current, {
      height,
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: cssVar("--app-muted"), attributionLogo: true },
      grid: { vertLines: { color: cssVar("--app-line") }, horzLines: { color: cssVar("--app-line") } },
      rightPriceScale: { borderColor: cssVar("--app-line") },
      timeScale: { borderColor: cssVar("--app-line") },
      localization: { locale: "en-US" },
    });
    const series = chart.addSeries(CandlestickSeries, {
      upColor: cssVar("--app-good"), downColor: cssVar("--app-bad"), borderVisible: false,
      wickUpColor: cssVar("--app-good"), wickDownColor: cssVar("--app-bad"),
    });
    series.setData(bars);
    chart.timeScale().fitContent();
    chartRef.current = chart;
    return () => {
      chart.remove();
      chartRef.current = null;
    };
  }, [bars, height, theme]);

  const first = bars[0]?.close;
  const last = bars[bars.length - 1]?.close;
  const change = first && last ? ((last / first - 1) * 100).toFixed(1) : null;
  return (
    <figure>
      {/* The library injects its attribution link into the container, so the text alternative sits beside it. */}
      <div ref={ref} />
      <p className="sr-only">{`${label} daily price chart for ${symbol}: ${bars.length} days, from ${first?.toFixed(2)} to ${last?.toFixed(2)} (${change}% change).`}</p>
      <figcaption className="mt-1 flex flex-wrap justify-between gap-2 text-[11px] text-muted">
        <span>
          {label} daily bars · {bars.length} sessions · change {change}%
        </span>
        <span>
          Charts by{" "}
          <a href="https://www.tradingview.com/" target="_blank" rel="noreferrer noopener" className="text-accent underline">
            TradingView
          </a>{" "}
          Lightweight Charts
        </span>
      </figcaption>
    </figure>
  );
}
