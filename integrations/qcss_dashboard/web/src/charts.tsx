// Charts built to the dataviz method: one y-axis per chart, thin 2px lines, a legend for >= 2 series, recessive grid,
// fixed categorical order (series-1..8 by entity, never by rank), hover readout on every plot.
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import uPlot from "uplot";

const css = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#888";
export const SERIES = (i: number) => `var(--series-${(i % 8) + 1})`;
const seriesHex = (i: number) => css(`--series-${(i % 8) + 1}`);

function useWidth<T extends HTMLElement>(): [React.RefObject<T | null>, number] {
  const ref = useRef<T>(null);
  const [w, setW] = useState(600);
  useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver(([e]) => setW(Math.max(200, Math.floor(e.contentRect.width))));
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);
  return [ref, w];
}

export type Line = { label: string; y: (number | null)[]; color?: number; dash?: boolean; points?: boolean; width?: number };

/** A line chart (uPlot): hover crosshair with a value readout, legend when there are two or more series. */
export function LineChart({ x, lines, xLabel, yLabel, height = 220, yRange, title }: {
  x: number[]; lines: Line[]; xLabel?: string; yLabel?: string; height?: number; yRange?: [number, number];
  title?: string;
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const plot = useRef<uPlot | null>(null);
  const key = useMemo(() => lines.map((l) => l.label).join("|"), [lines]);
  useEffect(() => {
    if (!ref.current || !x.length) return;
    const ink = css("--text-secondary"), grid = css("--grid");
    const axis = (label?: string): uPlot.Axis => ({
      stroke: ink, grid: { stroke: grid, width: 1 }, ticks: { stroke: grid, width: 1 }, label,
      labelFont: "11px system-ui, Segoe UI, sans-serif", font: "11px Consolas, ui-monospace, monospace", labelSize: 18,
    });
    const opts: uPlot.Options = {
      width, height, title,
      legend: { show: lines.length >= 2, live: true },
      cursor: { drag: { x: true, y: false } },
      scales: { x: { time: false }, y: yRange ? { range: () => yRange } : {} },
      axes: [axis(xLabel), axis(yLabel)],
      series: [{ label: xLabel ?? "x" }, ...lines.map((l, i) => ({
        label: l.label, stroke: seriesHex(l.color ?? i), width: l.width ?? 2, dash: l.dash ? [6, 4] : undefined,
        points: { show: !!l.points, size: 8, stroke: seriesHex(l.color ?? i), fill: css("--surface-1") },
        value: (_u: uPlot, v: number | null) => (v === null ? "—" : Math.abs(v) < 1e-3 && v !== 0 ? v.toExponential(2) : v.toFixed(4)),
      }))],
    };
    const data = [x, ...lines.map((l) => l.y)] as uPlot.AlignedData;
    plot.current?.destroy();
    plot.current = new uPlot(opts, data, ref.current);
    return () => { plot.current?.destroy(); plot.current = null; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [x, lines, key, width, height, xLabel, yLabel, yRange?.[0], yRange?.[1]]);
  return <div ref={ref} className="w-full" aria-label={title ?? yLabel ?? "chart"} role="img" />;
}

/** IQ-plane scatter (canvas): one cloud per prepared state, optional threshold line and centroids. */
export function IQScatter({ clouds, threshold, centroids, height = 280 }: {
  clouds: { label: string; points: [number, number][] }[]; threshold?: { rotation: number; value: number };
  centroids?: [number, number][]; height?: number;
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const canvas = useRef<HTMLCanvasElement>(null);
  const [hover, setHover] = useState<string>("");
  const bounds = useMemo(() => {
    const all = clouds.flatMap((c) => c.points);
    const xs = all.map((p) => p[0]), ys = all.map((p) => p[1]);
    const pad = (a: number[]) => { const lo = Math.min(...a), hi = Math.max(...a); const d = (hi - lo) * 0.08 || 1; return [lo - d, hi + d]; };
    return all.length ? { x: pad(xs), y: pad(ys) } : { x: [-1, 1], y: [-1, 1] };
  }, [clouds]);
  const size = Math.min(width, height * 1.6);
  useEffect(() => {
    const cv = canvas.current;
    if (!cv) return;
    const dpr = window.devicePixelRatio || 1;
    cv.width = size * dpr; cv.height = height * dpr;
    const g = cv.getContext("2d")!;
    g.scale(dpr, dpr);
    g.fillStyle = css("--surface-1"); g.fillRect(0, 0, size, height);
    const sx = (v: number) => 30 + ((v - bounds.x[0]) / (bounds.x[1] - bounds.x[0])) * (size - 40);
    const sy = (v: number) => height - 20 - ((v - bounds.y[0]) / (bounds.y[1] - bounds.y[0])) * (height - 30);
    g.strokeStyle = css("--grid"); g.lineWidth = 1;
    g.beginPath(); g.moveTo(sx(0), 0); g.lineTo(sx(0), height); g.moveTo(0, sy(0)); g.lineTo(size, sy(0)); g.stroke();
    clouds.forEach((c, i) => {
      g.fillStyle = seriesHex(i); g.globalAlpha = 0.55;
      for (const [x, y] of c.points) { g.beginPath(); g.arc(sx(x), sy(y), 2, 0, 2 * Math.PI); g.fill(); }
    });
    g.globalAlpha = 1;
    if (threshold) {
      // Points with Re(z e^{-i theta}) = threshold form a line perpendicular to the rotation direction.
      const ux = Math.cos(threshold.rotation), uy = Math.sin(threshold.rotation);
      const px = threshold.value * ux, py = threshold.value * uy, L = 1e3 * (bounds.x[1] - bounds.x[0] + bounds.y[1] - bounds.y[0]);
      g.strokeStyle = css("--text-primary"); g.setLineDash([5, 4]); g.lineWidth = 1.5;
      g.beginPath(); g.moveTo(sx(px - uy * L), sy(py + ux * L)); g.lineTo(sx(px + uy * L), sy(py - ux * L)); g.stroke(); g.setLineDash([]);
    }
    centroids?.forEach(([x, y], i) => {
      g.strokeStyle = css("--surface-1"); g.lineWidth = 2; g.fillStyle = seriesHex(i);
      g.beginPath(); g.arc(sx(x), sy(y), 6, 0, 2 * Math.PI); g.fill(); g.stroke();
    });
    g.fillStyle = css("--text-muted"); g.font = "10px ui-monospace";
    g.fillText("I →", size - 28, sy(0) - 4); g.fillText("Q ↑", sx(0) + 4, 12);
  }, [clouds, threshold, centroids, size, height, bounds]);
  const onMove = (e: React.MouseEvent) => {
    const r = (e.target as HTMLCanvasElement).getBoundingClientRect();
    const x = bounds.x[0] + ((e.clientX - r.left - 30) / (size - 40)) * (bounds.x[1] - bounds.x[0]);
    const y = bounds.y[0] + ((height - 20 - (e.clientY - r.top)) / (height - 30)) * (bounds.y[1] - bounds.y[0]);
    setHover(`I ${x.toExponential(2)}  Q ${y.toExponential(2)}`);
  };
  return (
    <div ref={ref} className="w-full">
      <canvas ref={canvas} style={{ width: size, height }} onMouseMove={onMove} onMouseLeave={() => setHover("")}
        role="img" aria-label="IQ plane scatter of integrated readout shots" />
      <div className="mt-1 flex flex-wrap items-center gap-3 text-[11px] text-ink2">
        {clouds.map((c, i) => <Legend key={c.label} i={i} label={`${c.label} (${c.points.length})`} />)}
        {threshold && <span className="text-mute">– – discriminator threshold</span>}
        <span className="num ml-auto text-mute">{hover}</span>
      </div>
    </div>
  );
}

export function Legend({ i, label }: { i: number; label: ReactNode }) {
  return <span className="inline-flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm" style={{ background: SERIES(i) }} />{label}</span>;
}

/** Matrix heatmap (SVG): sequential single hue (blue) for magnitude, value printed in every cell (small matrices). */
export function Heatmap({ m, rowLabels, colLabels, max = 1, digits = 3, title }: {
  m: number[][]; rowLabels: string[]; colLabels: string[]; max?: number; digits?: number; title?: string;
}) {
  const cell = 46;
  return (
    <figure>
      {title && <figcaption className="mb-1 text-[11px] text-mute">{title}</figcaption>}
      <svg width={40 + colLabels.length * cell} height={22 + rowLabels.length * cell} role="img" aria-label={title ?? "matrix"}>
        {colLabels.map((c, j) => <text key={c} x={40 + j * cell + cell / 2} y={14} textAnchor="middle" fontSize={11} fill="var(--text-muted)">{c}</text>)}
        {m.map((row, i) => (
          <g key={i}>
            <text x={34} y={22 + i * cell + cell / 2 + 4} textAnchor="end" fontSize={11} fill="var(--text-muted)">{rowLabels[i]}</text>
            {row.map((v, j) => {
              const a = Math.max(0, Math.min(1, Math.abs(v) / max));
              return (
                <g key={j}>
                  <rect x={40 + j * cell + 1} y={22 + i * cell + 1} width={cell - 2} height={cell - 2} rx={4}
                    fill={`color-mix(in oklab, var(--series-1) ${Math.round(a * 85 + 5)}%, var(--surface-2))`}>
                    <title>{`${rowLabels[i]} → ${colLabels[j]}: ${v.toFixed(digits)}`}</title>
                  </rect>
                  <text x={40 + j * cell + cell / 2} y={22 + i * cell + cell / 2 + 4} textAnchor="middle" fontSize={10.5}
                    fill={a > 0.55 ? "#fff" : "var(--text-primary)"} className="num">{v.toFixed(digits)}</text>
                </g>
              );
            })}
          </g>
        ))}
      </svg>
    </figure>
  );
}

export type GanttRow = { row: string; start: number; end: number; label: string; color: number; note?: string; marker?: boolean };

/** Timeline (SVG): one lane per channel or generator; instants as markers. Hover shows exact times. */
export function Gantt({ items, unit = "ns", height }: { items: GanttRow[]; unit?: string; height?: number }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const rows = [...new Set(items.map((i) => i.row))];
  const t0 = Math.min(0, ...items.map((i) => i.start));
  const t1 = Math.max(...items.map((i) => i.end), t0 + 1);
  const lane = 26, left = 110, h = height ?? rows.length * lane + 26;
  const sx = (t: number) => left + ((t - t0) / (t1 - t0)) * (width - left - 12);
  const ticks = Array.from({ length: 6 }, (_, k) => t0 + (k * (t1 - t0)) / 5);
  return (
    <div ref={ref} className="w-full overflow-x-auto">
      <svg width={width} height={h} role="img" aria-label="timeline">
        {ticks.map((t) => (
          <g key={t}>
            <line x1={sx(t)} x2={sx(t)} y1={0} y2={h - 18} stroke="var(--grid)" />
            <text x={sx(t)} y={h - 4} textAnchor="middle" fontSize={10} fill="var(--text-muted)" className="num">{t.toFixed(t1 - t0 < 20 ? 1 : 0)} {unit}</text>
          </g>
        ))}
        {rows.map((r, i) => <text key={r} x={left - 8} y={i * lane + 17} textAnchor="end" fontSize={11} fill="var(--text-secondary)">{r}</text>)}
        {items.map((it, k) => {
          const y = rows.indexOf(it.row) * lane + 4;
          const x = sx(it.start), w = Math.max(2, sx(it.end) - x);
          return it.marker ? (
            <g key={k}><line x1={x} x2={x} y1={y - 2} y2={y + 20} stroke={SERIES(it.color)} strokeWidth={2} />
              <circle cx={x} cy={y + 9} r={4} fill={SERIES(it.color)} stroke="var(--surface-1)" strokeWidth={2} />
              <title>{`${it.label} @ ${it.start.toFixed(2)} ${unit}${it.note ? ` — ${it.note}` : ""}`}</title></g>
          ) : (
            <g key={k}>
              <rect x={x} y={y} width={w} height={18} rx={4} fill={SERIES(it.color)} opacity={0.85} stroke="var(--surface-1)" strokeWidth={2} />
              {w > 48 && <text x={x + 5} y={y + 13} fontSize={10.5} fill="#fff">{it.label}</text>}
              <title>{`${it.label}: ${it.start.toFixed(2)} → ${it.end.toFixed(2)} ${unit}${it.note ? ` — ${it.note}` : ""}`}</title>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

/** Bloch sphere (SVG, fixed oblique camera): the vector, its trajectory, and the axes |0>, |1>, |+>, |+i>. */
export function Bloch({ vec, path, size = 220, label }: { vec: number[]; path?: number[][]; size?: number; label?: string }) {
  const r = size * 0.38, c = size / 2;
  const P = ([x, y, z]: number[]): [number, number] => [c + r * (y - 0.45 * x), c - r * (z - 0.25 * x)];
  const ring = (f: (t: number) => number[]) => Array.from({ length: 73 }, (_, k) => P(f((k / 72) * 2 * Math.PI)).join(",")).join(" ");
  const tip = P(vec);
  const len = Math.hypot(vec[0], vec[1], vec[2]);
  return (
    <figure className="inline-block text-center">
      <svg width={size} height={size} role="img" aria-label={`Bloch vector x ${vec[0].toFixed(2)}, y ${vec[1].toFixed(2)}, z ${vec[2].toFixed(2)}`}>
        <circle cx={c} cy={c} r={r} fill="none" stroke="var(--grid)" />
        <polyline points={ring((t) => [Math.cos(t), Math.sin(t), 0])} fill="none" stroke="var(--grid)" strokeDasharray="3 3" />
        <polyline points={ring((t) => [Math.cos(t), 0, Math.sin(t)])} fill="none" stroke="var(--grid)" strokeDasharray="3 3" />
        {[[[0, 0, 1], "|0⟩"], [[0, 0, -1], "|1⟩"], [[1, 0, 0], "|+⟩"], [[0, 1, 0], "|+i⟩"]].map(([v, t]) => {
          const [x, y] = P(v as number[]);
          return <text key={t as string} x={x} y={y} fontSize={10} fill="var(--text-muted)" textAnchor="middle" dy={(v as number[])[2] > 0 ? -4 : 12}>{t as string}</text>;
        })}
        {path && path.length > 1 && <polyline points={path.map((v) => P(v).join(",")).join(" ")} fill="none" stroke="var(--series-2)" strokeWidth={1.5} opacity={0.9} />}
        <line x1={c} y1={c} x2={tip[0]} y2={tip[1]} stroke="var(--series-1)" strokeWidth={2.5} />
        <circle cx={tip[0]} cy={tip[1]} r={5} fill="var(--series-1)" stroke="var(--surface-1)" strokeWidth={2} />
      </svg>
      <figcaption className="num text-[11px] text-mute">{label ?? ""} |r| = {len.toFixed(3)} (1 = pure)</figcaption>
    </figure>
  );
}
