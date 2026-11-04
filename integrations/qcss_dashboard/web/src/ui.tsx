import katex from "katex";
import { useMemo, useState, type ReactNode } from "react";
import { useFieldDoc, useRegistry, type FieldDoc } from "./registry";

export const cx = (...c: (string | false | null | undefined)[]) => c.filter(Boolean).join(" ");

export function Panel({ title, subtitle, actions, children, className, explain }: {
  title: ReactNode; subtitle?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string;
  explain?: ReactNode;
}) {
  return (
    <section className={cx("min-w-0 rounded-lg border border-line bg-s1", className)}>
      <header className="flex items-start gap-3 border-b border-line px-4 py-2.5">
        <div className="min-w-0 flex-1">
          <h2 className="text-[13px] font-semibold tracking-wide text-ink">{title}</h2>
          {subtitle && <p className="mt-0.5 text-[12px] text-mute">{subtitle}</p>}
        </div>
        {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
      </header>
      {explain && <Explainer>{explain}</Explainer>}
      <div className="p-4">{children}</div>
    </section>
  );
}

/** The margin note under a panel header: hidden at depth "plain" only when it is marked expert. */
export function Explainer({ children, expert }: { children: ReactNode; expert?: boolean }) {
  const { depth } = useRegistry();
  if (expert && depth === "plain") return null;
  return <div className="border-b border-line bg-s2/50 px-4 py-2 text-[12px] leading-relaxed text-ink2">{children}</div>;
}

/** Shown only at the given depth or deeper. */
export function Deep({ at, children }: { at: "expert" | "source"; children: ReactNode }) {
  const { depth } = useRegistry();
  const ok = at === "expert" ? depth !== "plain" : depth === "source";
  return ok ? <>{children}</> : null;
}

type Tone = "neutral" | "accent" | "truth" | "good" | "warn" | "crit" | "lab";
export function Badge({ children, tone = "neutral", title }: { children: ReactNode; tone?: Tone; title?: string }) {
  const t = {
    neutral: "border-line text-ink2", accent: "border-accent/60 text-accent", lab: "border-accent/60 text-accent",
    truth: "border-truth/70 text-truth border-dashed", good: "border-good/60 text-good",
    warn: "border-warn/60 text-warn", crit: "border-crit/70 text-crit",
  }[tone];
  return (
    <span title={title} className={cx("inline-flex items-center gap-1 whitespace-nowrap rounded border px-1.5 py-px text-[10.5px] font-medium uppercase tracking-wider", t)}>
      {children}
    </span>
  );
}

export const TruthBadge = () => <Badge tone="truth" title="Hidden truth: lab clients never see this">◉ truth</Badge>;
export const LabBadge = () => <Badge tone="lab" title="What a lab client sees over the lab link">lab view</Badge>;

export function Stat({ label, value, unit, hint, tone }: {
  label: ReactNode; value: ReactNode; unit?: string; hint?: ReactNode; tone?: "good" | "warn" | "crit";
}) {
  const c = tone === "good" ? "text-good" : tone === "warn" ? "text-warn" : tone === "crit" ? "text-crit" : "text-ink";
  return (
    <div className="min-w-0">
      <div className="text-[11px] uppercase tracking-wider text-mute">{label}</div>
      <div className={cx("num truncate text-[18px] leading-7", c)}>
        {value}
        {unit && <span className="ml-1 text-[12px] text-mute">{unit}</span>}
      </div>
      {hint && <div className="text-[11px] text-mute">{hint}</div>}
    </div>
  );
}

export function Button({ children, onClick, kind = "default", disabled, title, type = "button" }: {
  children: ReactNode; onClick?: () => void; kind?: "default" | "primary" | "danger" | "ghost"; disabled?: boolean;
  title?: string; type?: "button" | "submit";
}) {
  const k = {
    default: "border-line bg-s2 hover:bg-s3 text-ink", primary: "border-accent bg-accent/90 hover:bg-accent text-white",
    danger: "border-crit/70 bg-crit/15 hover:bg-crit/25 text-crit", ghost: "border-transparent hover:bg-s2 text-ink2",
  }[kind];
  return (
    <button type={type} title={title} disabled={disabled} onClick={onClick}
      className={cx("inline-flex h-7 items-center gap-1.5 whitespace-nowrap rounded-md border px-2.5 text-[12px] font-medium disabled:cursor-not-allowed disabled:opacity-50", k)}>
      {children}
    </button>
  );
}

export function Select({ value, onChange, options, label, className }: {
  value: string; onChange: (v: string) => void; options: (string | { value: string; label: string })[]; label?: ReactNode;
  className?: string;
}) {
  return (
    <label className={cx("inline-flex items-center gap-1.5 text-[12px] text-mute", className)}>
      {label}
      <select value={value} onChange={(e) => onChange(e.target.value)}
        className="h-7 max-w-56 rounded-md border border-line bg-s2 px-2 text-[12px] text-ink">
        {options.map((o) => typeof o === "string"
          ? <option key={o} value={o}>{o}</option>
          : <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </label>
  );
}

export function NumberField({ label, value, onChange, step, min, max, unit, docKey, width = "w-24" }: {
  label: ReactNode; value: number; onChange: (v: number) => void; step?: number; min?: number; max?: number;
  unit?: string; docKey?: string; width?: string;
}) {
  return (
    <label className="flex flex-col gap-1 text-[11px] text-mute">
      <span className="flex items-center gap-1">{label}{docKey && <InfoTip docKey={docKey} />}</span>
      <span className="flex items-center gap-1">
        <input type="number" value={Number.isFinite(value) ? value : ""} step={step} min={min} max={max}
          onChange={(e) => onChange(e.target.valueAsNumber)}
          className={cx("num h-7 rounded-md border border-line bg-s2 px-2 text-[12px] text-ink", width)} />
        {unit && <span className="text-[11px]">{unit}</span>}
      </span>
    </label>
  );
}

export function Toggle({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label: ReactNode }) {
  return (
    <label className="inline-flex cursor-pointer items-center gap-2 text-[12px] text-ink2">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} className="accent-[var(--accent)]" />
      {label}
    </label>
  );
}

export function Tabs<T extends string>({ tabs, value, onChange }: {
  tabs: { id: T; label: ReactNode }[]; value: T; onChange: (t: T) => void;
}) {
  return (
    <div role="tablist" className="flex flex-wrap gap-1 border-b border-line">
      {tabs.map((t) => (
        <button key={t.id} role="tab" aria-selected={value === t.id} onClick={() => onChange(t.id)}
          className={cx("-mb-px border-b-2 px-3 py-1.5 text-[12px]", value === t.id ? "border-accent text-ink" : "border-transparent text-mute hover:text-ink2")}>
          {t.label}
        </button>
      ))}
    </div>
  );
}

export function StateBox({ state, error, empty, children, onRetry }: {
  state: "loading" | "error" | "empty" | "ok"; error?: unknown; empty?: ReactNode; children?: ReactNode; onRetry?: () => void;
}) {
  if (state === "loading") {
    return <div className="flex items-center gap-2 py-8 text-mute" role="status"><Spinner /> computing with QCSS…</div>;
  }
  if (state === "error") {
    return (
      <div role="alert" className="rounded-md border border-crit/50 bg-crit/10 p-3 text-[12px] text-ink2">
        <div className="font-medium text-crit">✕ {error instanceof Error ? error.message : String(error)}</div>
        {onRetry && <div className="mt-2"><Button onClick={onRetry}>Retry</Button></div>}
      </div>
    );
  }
  if (state === "empty") return <div className="py-8 text-center text-mute">{empty}</div>;
  return <>{children}</>;
}

export const Spinner = () => <span className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-mute border-t-accent" />;

export function Equation({ tex, block }: { tex: string; block?: boolean }) {
  const html = useMemo(() => {
    try {
      return katex.renderToString(tex, { throwOnError: false, displayMode: !!block });
    } catch {
      return tex;
    }
  }, [tex, block]);
  return <span className={block ? "block overflow-x-auto py-1" : ""} dangerouslySetInnerHTML={{ __html: html }} />;
}

export function SourceRef({ path }: { path: string }) {
  if (!path) return null;
  return <code className="rounded bg-s3 px-1 py-px font-mono text-[11px] text-ink2" title="Source in the QCSS repository">{path}</code>;
}

export function constraintText(c: Record<string, number> | undefined): string {
  if (!c) return "";
  const parts: string[] = [];
  if (c.gt !== undefined) parts.push(`> ${c.gt}`);
  if (c.ge !== undefined) parts.push(`≥ ${c.ge}`);
  if (c.lt !== undefined) parts.push(`< ${c.lt}`);
  if (c.le !== undefined) parts.push(`≤ ${c.le}`);
  return parts.join(", ");
}

/** The layered explanation of one registry field: plain summary, expert detail, equation and source. */
export function FieldExplain({ doc, compact }: { doc: FieldDoc; compact?: boolean }) {
  const { depth } = useRegistry();
  const range = constraintText(doc.constraints);
  return (
    <div className="space-y-1.5 text-[12px] leading-relaxed text-ink2">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="font-mono text-ink">{doc.model}.{doc.field}</span>
        {doc.unit && <Badge>{doc.unit}</Badge>}
        <Badge tone={doc.apply === "live" ? "good" : doc.apply === "restart" ? "warn" : "accent"} title={`apply: ${doc.apply}`}>{doc.apply}</Badge>
        {doc.inert && <Badge tone="crit" title="Validated but not used by the simulator at runtime">inert</Badge>}
        {doc.layer === "B" && <TruthBadge />}
      </div>
      <p>{doc.summary}</p>
      {depth !== "plain" && !compact && doc.detail && <p className="text-mute">{doc.detail}</p>}
      {depth !== "plain" && !compact && (
        <p className="num text-[11px] text-mute">
          type {doc.type}
          {doc.default !== null && doc.default !== undefined && ` · default ${JSON.stringify(doc.default)}`}
          {range && ` · ${range}`}
          {doc.required && " · required"}
        </p>
      )}
      {depth !== "plain" && doc.equation && <Equation tex={doc.equation} block />}
      {depth === "source" && doc.source && <SourceRef path={doc.source} />}
    </div>
  );
}

/** A small (i) button that opens a field's explanation in a popover. */
export function InfoTip({ docKey }: { docKey: string }) {
  const doc = useFieldDoc(docKey);
  const [open, setOpen] = useState(false);
  if (!doc) return null;
  return (
    <span className="relative inline-block align-middle">
      <button type="button" aria-label={`Explain ${doc.field}`} aria-expanded={open} onClick={() => setOpen((o) => !o)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        className="grid h-4 w-4 place-items-center rounded-full border border-line text-[9px] text-mute hover:border-accent hover:text-accent">i</button>
      {open && (
        <div role="tooltip" className="absolute left-0 top-5 z-50 w-80 rounded-md border border-line bg-s2 p-3 shadow-xl">
          <FieldExplain doc={doc} />
        </div>
      )}
    </span>
  );
}

export function KV({ rows }: { rows: [ReactNode, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 text-[12px]">
      {rows.map(([k, v], i) => (
        <div key={i} className="contents">
          <dt className="text-mute">{k}</dt>
          <dd className="num min-w-0 truncate text-ink">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

export const fmt = (v: number | null | undefined, d = 3) =>
  v === null || v === undefined || !Number.isFinite(v)
    ? "—"
    : Math.abs(v) >= 1e5 || (Math.abs(v) < 1e-3 && v !== 0) ? v.toExponential(2) : v.toFixed(d);
